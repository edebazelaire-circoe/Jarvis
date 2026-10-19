# 05 — Documentation levels and required canonical updates

Slice 00 must verify current documentation levels at HEAD. Planning-time state and target are:

| Concept | Planning-time state | Target / required update |
| --- | --- | --- |
| Control Center shell geometry/layers | Level 3 (`docs/control-center-shell.md`) | Keep Level 3; update zones, layers, tokens, controls and conformance tests in same commits as UI moves |
| Board contract / Board memory | Level 3 (`docs/boards.md`) | Keep Level 3; change type semantics, immutability and remove independent user mode ownership |
| Interaction mode | Level 3 (`docs/interaction-mode.md`) | Explicitly retire/reframe as derived compatibility/runtime policy; no stale docs claiming it is an independent user product axis |
| Capture | Level 3 (`docs/capture.md`) | Keep owner/state contract; update UI section from three primary wheel wedges to Capture submenu + transient indicators |
| Scene visibility/archive/selection | Level 3 (`docs/scene-model.md`, `docs/scene-selection-batch.md`) | Reuse; add/document any semantic Dossier integration without redefining hidden/archive |
| Board Dossier projection | New concept | Reach at least Level 2 before UI work; preferably Level 3 when service/API + conformance tests are implemented |
| Dossier UI / voice commands | New UI projection | Document navigation, routes/tools, accessibility and manual/voice parity; Level 2/3 depending reusable contract depth |
| Completed-task lifecycle follow-up | Idea only | Remains an Issue in this task; no canonical product doc update unless separately approved |

## Documentation update rule

No Slice may change product semantics only in comments/tests. Update the canonical contract in the same Slice that changes the authoritative implementation. Remove or mark superseded statements; do not leave contradictory “old truth” in top-level docs.

Particular stale statements that must not survive the final task:

- `docs/boards.md`: a meeting Board may independently be in assistant interaction mode.
- `docs/interaction-mode.md`: interaction mode is a separately user-chosen product axis persisted per Board.
- README section teaching users to switch SIMPLE/PRESENTATION as a separate mode.
- shell docs listing the old bottom-left interaction-mode HUD and old top-left Board HUD placement.
- capture docs saying Video/Screenshot/Audio are first-level wheel wedges after the new Capture category ships.

Added by Slice 00 (HEAD `2fb66040`): levels above verified (shell, Boards, interaction mode, capture, scene and scene selection are Level 3 contracts with conformance tests). Further stale statements that must not survive:

- `docs/control-center-shell.md`: *Status centre* row 3 (`#hiddenEye`), *Zones* `top-left` (`#boardsHud`, `.state`) and `bottom-left` (`#interactionModeHud`), *Global launcher* rows « Board / Interaction mode unchanged », the mode-control rungs and 254 px insets, *Tool wheel* « exactly four primary wedges ».
- `docs/scene-model.md` › *Visibility vs disposition*: « toggled by the eye `#hiddenEye` of the status centre ».
- `docs/presentation-studio.md`: the interaction-mode HUD kept live over Variants (`data-keep-live="run"`) as « the way out of PRESENTATION », the reload band placed against `#interactionModeHud`, restore « reapplies the stored per-Board preference ».
- `jarvis/runtime/claude_local.py` prompt line « passe en mode présentation / simple / réunion ».
