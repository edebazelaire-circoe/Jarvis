# Architecture target and boundaries


## User-facing composition


```
Jarvis Presentation workspace
  |-- Remotion Studio [native editor / trusted authoring workspace]
  |-- Variants [Jarvis versions, branch, compare, metadata, embedded preview]
            |-- Remotion Player [single media transport + composition clock]
  |-- Presenter/Shadow lane [optional speech/cues bound to presentation score]
```


The two views may coexist as destinations but there is no competing Jarvis floating stage viewer, second transport logic or duplicated state of playback. When native Studio provides its own local preview for editing, that preview is not a second Jarvis-owned playback engine or a competing global time authority in Variants.


## Canonical ownership


| Concern | Proposed authority / direction |
| --- | --- |
| Scene and composition source | Existing canonical Remotion scene/Prefab source and exact version pins; add safe project authoring workspace if needed |
| Variant identity and operations | Core Presentation Studio variant domain and services |
| Composed video time | One Remotion composition time/frame base; pure scene interval map derived from manifest |
| UI transport and controls | One browser adapter to Remotion Player; redundant Control Center band uses same store or disappears |
| Presenter score/cues | Core-owned score state; maps to media frame only when explicit; never secretly shortens video scenes |
| Viewer lifecycle | One intended Variants preview and fullscreen media surface; old floating viewer removed |
| Native Studio lifecycle | Existing managed local Remotion Studio runner and explicit trust/health boundary, improved for authoring |
| Preview versus render | HMR/live preview is not MP4 render; export remains explicit snapshot render |
| Provenance/data | Existing Boards/Artifacts/Prefabs/scene variants; no parallel catalog |


## Actual modules to inspect (not presumed edit list)


- `jarvis/runtime/control_center_presentation_studio_player.js`: existing playback band and multiple control surfaces.
- `jarvis/runtime/control_center_presentation_studio_explorer*.js`: Variants/Explorer UI and preview.
- `jarvis/runtime/control_center_presentation_window.js`: separate presentation window.
- `jarvis/runtime/control_center_presentation_rail.js`: presentation rail, state and entry points.
- `jarvis/runtime/control_center_remotion_stage.js`, `control_center_remotion_frame.js`, `control_center_remotion_stage.html`: per-scene Player stage and protocol.
- `jarvis/core/presentation_studio_playback.py`, `presentation_studio_autoplay.py`, `presentation_studio_presenter.py`: existing score/play/auto authority.
- `jarvis/domain/remotion_timeline.py`, `presentation_studio_playback_requests.py`: time mapping and default manual `Scope`.
- `jarvis/core/remotion_player.py`, `jarvis/adapters/remotion_compiler.py`, `jarvis/capabilities/remotion/runtime-host.mjs`: Remotion integration.
- `jarvis/adapters/remotion_studio_runner.py`, `jarvis/core/remotion_studio_service.py`, `jarvis/runtime/control_center_remotion_studio.js`: native Studio process.
- `jarvis/runtime/presentation_playbooks.py`, authoring policy/gate/TSX modules: agent workflow.


## State semantics


- Maintain one canonical composition frame; derive total duration, normalized scene index, local frame, local progress, transition overlap and UI labels from it.
- Local scene seek is `scene.startFrame + requestedOffset` (or an explicitly defined transition-relative variant). Move to next is based on scene boundary from composition, not previous local frame.
- Pausing/resuming must preserve exact composition frame; replay first frame is explicit action. End-of-sequence must never wrap accidentally.
- Manual presenter mode is separate from continuous video; it can hold at a score anchor but must never impersonate an arbitrary video per-slide length.


## Security, licensing and migration


Native Studio is not a secure executor of untrusted code. Existing sandbox policy and explicit user acknowledgment must be retained or upgraded, not removed to improve convenience. Any agent-native workspace requires source control, artifact pins, diff/audit, safety approval where required, versioning, rollback and no silent writes. Existing data/variants retain logical identity. No auto-fallback to Slidecar on Remotion errors.