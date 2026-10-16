# Jarvis - Orbital Control Center UI, contextual tool wheel, and active workspace rail

**Project:** Jarvis  
**Handoff slug:** `jarvis-board-orbital-ui-workspace-rail`  
**Planning date:** 2026-10-15  
**Repository inspected:** `edebazelaire-circoe/Jarvis`, default branch `main`  
**Reference commit observed during planning:** `57f28a7472577f8a193303023a99b026855f09ba` (latest commit returned by GitHub during planning; PM must re-check HEAD before dispatch)  
**Implementation status:** planned only. This handoff does not claim any product code has been changed.

## Execution entry point

Start with `slices/TODO.md`, then execute `slices/00-project-manager/SLICE.md` yourself. Slice 00 is a readiness gate, not a coding slice. No implementation slice may be delegated before Slice 00 concludes `READY`.

## Product objective

Transform the current Control Center shell from a collection of independent left/right bars into a coherent, low-clutter orbital workspace while preserving Jarvis' existing canonical owners and runtime guarantees.

The user-approved target is represented by `assets/target-ui-reference.png`. The current UI screenshot is preserved as `assets/current-ui.png`. The target image is a **design reference**, not a license to replace proven runtime state machines with local UI state or to delete functionality merely because it is not visible in the mockup.

The central Board/constellation remains the hero surface. The transformation is around it:

1. Replace the always-present left tool stacks with a **retractable semi-circular tool wheel** anchored to the left edge.
2. Reduce the initial wheel to four product functions only: **Selection**, **Video**, **Screenshot**, **Audio**. It must be extensible, but it must not be filled with speculative tools.
3. Selection exposes exactly two control modes: **Mouse** and **Bare Hands**. Remove other selection-mode choices from this surface.
4. Add intelligent Mouse takeover from Bare Hands on deliberate mouse use, while return to Bare Hands stays explicit (wheel or Jarvis command).
5. Reuse the canonical capture owner and capture status truth for Video/Audio/Screenshot. The wheel is a view/controller, not a second capture state machine.
6. Move the current presentation list from the left into a **right-side active workspace rail** with rich previews, recognizable media/document types, status, and current-context semantics.
7. Remove the bottom-center `F9` start hint and use that visual territory for a compact **notification/status center**.
8. Replace the verbose hidden-object capsule with one **eye / eye-off** control.
9. Keep the bottom-left interaction mode control as a permanent context anchor; Board access must remain available and may be colocated in that cluster if the canonical Board control can be preserved without duplicating state.
10. Simplify the top chrome and right-side tool clutter while preserving every still-required function through an equivalent discoverable route.

## Non-negotiable behavior

### Tool wheel

- At rest the wheel is hidden except for a small permanent visual anchor/core peeking from the left edge.
- Mouse activation: moving the pointer to the left-edge hotspot/anchor reveals the wheel.
- Bare Hands activation: extending the hand or two fingers toward the left reveals the wheel. Pointing/hovering selects a wedge; the Bare Hands pinch/click gesture activates it.
- Selected wedge receives strong but restrained cyan emphasis and a readable label.
- Wheel is context-sensitive. Global settings, diagnostics, account/runtime status and other global functions do not get dumped into it.
- Persistent modes stay selected; one-shot actions return to the prior interaction state when finished.

### Selection and input arbitration

- `Selection` expands to exactly `Mouse` and `Bare Hands`.
- Existing Bare Hands iconography on this selector is to be redesigned; do not reuse the disliked hand icon as-is.
- If Bare Hands is active, an explicit mouse click switches control to Mouse immediately.
- Meaningful mouse movement also switches to Mouse, but micro-movement/jitter must not. The implementation needs hysteresis/debouncing and runtime tuning, not a fragile one-pixel trigger.
- Switching from Mouse back to Bare Hands is explicit only: the user chooses Bare Hands or asks Jarvis. Do not auto-flap between modes.
- Do not create a second lifecycle owner. Existing Bare Hands lifecycle/status remains authoritative.

### Capture controls

- Video, Screenshot, and Audio are direct wheel actions.
- **Audio:** first activation starts; second activation stops; running duration/state remains visible after the wheel retracts. Secondary activation (right-click, thumb+middle pinch, ContextMenu/Shift+F10; never long press, see docs/06 D4) opens available source choices.
- **Video:** first activation starts immediately; second activation stops; persistent `REC + duration` remains visible after wheel retracts. Secondary activation (right-click, thumb+middle pinch, ContextMenu/Shift+F10; never long press, see docs/06 D4) opens available capture target choices.
- **Screenshot:** activation captures and saves immediately. Then show a short-lived non-blocking thumbnail with quick actions: open, annotate, send to Jarvis, delete. Ignoring the preview must never interrupt work.
- **Screenshot/Video targeting:** simple activation uses the current/default target. A secondary/long activation exposes supported target choices. The implementation must surface only targets the current capture contract can actually execute; no fake UI choices.
- Capture state, timers, errors, recovery, multi-tab truth and stop behavior stay owned by Core. The current capture rail already follows this architecture and should be migrated/refactored rather than bypassed.

### Bottom status center

- Remove the bottom-center `F9 - DEMARRER` visual hint from this surface.
- Recompose the existing background notification pills into a horizontal, compact status strip centered near the bottom.
- Minimum categories: warning/alert (orange), completed tasks (check/task-done + count), pending questions (question/help + count). A fourth category is allowed only if it maps to a canonical existing category; do not invent a meaningless counter.
- Icons should be readable and slightly larger than the current tiny pills without becoming large cards.
- Clicking a category should preserve the existing drill-down/popover behavior where applicable.
- Recording indicators may live adjacent to this center when active, but must remain visually distinct from notification counters.

### Hidden objects

- Remove the text/count capsule currently describing hidden objects shown/hidden.
- Replace it with a single compact eye / eye-off toggle.
- The eye reflects current state and toggles the same canonical scene visibility behavior; it must not become its own hidden-object state store.

### Right active workspace rail

The right rail is **not a generic file library**. It is the visible working set for the current context (Board/session/workspace): presentations, documents, videos, images and related artifacts currently linked or actively relevant.

Each row/card should provide:
- a recognizable preview thumbnail, not a monogram-only square;
- a recognizable type treatment (PowerPoint, Google Slides, video, image, etc.) when the type is known;
- short title and useful lightweight metadata;
- state indicator;
- click to open/foreground the item in its appropriate Jarvis surface;
- existing context actions preserved where they remain applicable.

Status language requested by the user:
- blue: currently being worked on;
- green: ready/done;
- yellow: changed/new since last review, requires attention.

Existing canonical `problem`/error states must **not** be silently relabeled as yellow update states. Preserve an explicit exceptional/error treatment if the backend reports one. The PM must reconcile the presentation rail's existing `working/done/problem` model with the broader workspace model before implementation.

## Current implementation evidence discovered during planning

The following are starting points, not immutable instructions. Re-read at HEAD in Slice 00.

- `jarvis/runtime/control_center.html`
  - bottom-center `#voiceHint` currently renders `F9 - DEMARRER`;
  - right vertical `.dock` and right-side `.bgpills` currently compete for attention;
  - the file owns a detailed z-index registry; changing layout without updating/validating it is unsafe.
- `jarvis/runtime/control_center_barehands_hud.js`
  - current Bare Hands lifecycle projection and tool palette;
  - canonical lifecycle seam; UI must not create a parallel lifecycle state.
- `jarvis/runtime/control_center_capture_rail.js`
  - screenshot/audio/screen-recording controls already exist;
  - Core `/api/captures/status` is authoritative;
  - timers come from Core timestamps; UI does not paint optimistic capture truth;
  - status loss and privacy-first stop behavior are already handled.
- `jarvis/runtime/control_center_interaction_mode.js`
  - bottom-left SIMPLE/PRESENTATION/REUNION control;
  - canonical state comes from `/api/status`; writes go through `/api/interaction-mode` then re-read.
- `jarvis/runtime/control_center_presentation_rail.js`
  - current rail is on the left, monogram + title + status dot;
  - canonical data from `/api/presentation-studio/rail`;
  - existing `working`, `done`, `problem` states and context menu actions;
  - current visibility/pinning/studio behavior must be preserved or deliberately superseded.
- `jarvis/runtime/control_center_scene_page.js`
  - central scene and hidden/archive interactions.
- `docs/capture.md`, `docs/artifacts.md`, `docs/interaction-mode.md`, `docs/boards.md`, presentation documentation
  - canonical domain/service/API contracts to preserve.

## Design direction

Use the approved reference as the art-direction baseline:

- near-black/navy background with restrained glass surfaces;
- thin cyan/blue strokes and glows, not broad neon fills;
- orange/yellow/green used semantically, not decoratively;
- large empty breathing room around the central Board;
- shallow panels, compact cards, disciplined radii;
- typography should remain highly legible and consistent with current Jarvis product language;
- motion should explain state change (wheel reveal, selection focus, recording state) and respect `prefers-reduced-motion`;
- no permanent UI block should visually outweigh the Board itself.

The exact screenshot proportions are guidance. Responsive behavior, accessibility, existing Studio overlays, presentation runtime, menus, and modal stacking take precedence over pixel imitation.

## Planning boundaries / unknowns deliberately left for PM audit

- Exact mouse-movement threshold for takeover is a tunable interaction parameter. Define from measured deliberate movement, add hysteresis, and prove no jitter flapping.
- Secondary activation mapping (resolved in docs/06 D4: the existing `contextmenu` channel) must reuse the current input/gesture vocabulary where possible. Do not invent a new Bare Hands gesture if an existing canonical gesture can represent secondary activation.
- Exact default screen-capture target must preserve current behavior unless product evidence supports changing it.
- The exact fourth notification category is not locked.
- Rich thumbnails for every external format may require new preview providers. The rail must degrade gracefully to a typed placeholder when a real preview is unavailable; never fake a first-slide image.
- Whether Board switching is fully integrated into the bottom-left mode capsule or colocated as a sibling control depends on the canonical Board control and accessibility constraints. The user requirement is that bottom-left remains the durable mode/Board context zone, not that state ownership be merged.

## Required QA discipline

Every implementation Slice receives `qa-verification`. Every code Slice receives `code-review`. Every runtime/UI Slice receives `runtime-validation`. Any agent/runtime contract change receives `agent-trace-analysis` on real traces. Code slices run `/caveman` and `/coding-guideline`; frontend slices additionally run `/impeccable` and use a Claude implementation/review agent when supported by the host.

No one may stop/restart the user's live Jarvis instance without explicit permission. Runtime validation must use an isolated instance/worktree/data root unless the user explicitly authorizes live testing.
