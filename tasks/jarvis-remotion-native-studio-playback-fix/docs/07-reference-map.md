# Project source references (inspection starting points)


Repository: https://github.com/edebazelaire-circoe/Jarvis ; inspected commit reference `d2332e61c0e384d1e75d7d31a81efb730254eb6e` (2026-10-10 UTC). Always refresh HEAD.


- `docs/presentation-studio.md` - Studio variants, score, playback, controls, authoring, ownership.
- `docs/presentation-studio-release.md` - existing release tests and unresolved Human acceptance.
- `docs/presentation-mode.md` - distinct Presentation interaction mode, cues/voice ownership.
- `docs/presentation-engine.md` - engine choice and no silent fallback.
- `docs/remotion-runtime.md`, `docs/remotion-source.md`, `docs/remotion-isolation.md`, `docs/remotion-studio.md`, `docs/remotion-render.md` - native packages, source, sandbox, Studio, export.
- `docs/remotion-integration-release.md` - actual machine evidence and open Human/licensing conditions.
- `docs/presentation-production.md`, `jarvis/runtime/presentation_playbooks.py` - agent production workflow and its limits.
- `tasks/jarvis-interactive-presentation-studio/` and `tasks/jarvis-remotion-presentation-integration/` - historical handoffs. Their Slices report green code but do NOT override the user's real visual repro.
- `jarvis/runtime/control_center_presentation_studio_player.js` - comment describes playback band, 500ms polling and `manual|scene|all` controls.
- `jarvis/domain/presentation_studio_playback_requests.py` - `Scope.MANUAL` default; scene/all advanced chaining.
- `jarvis/runtime/control_center_presentation_rail.js` - 158px normal rail, 188px Studio side margin; geometry deferred until sketch.
- `jarvis/runtime/control_center_remotion_stage.js` and `control_center_remotion_frame.js` - browser sandbox and timeline follower.


Known version pin in `jarvis/capabilities/remotion/package.json` at inspected HEAD: Remotion packages 4.0.534, React 19.3.0. These are not a mandate to upgrade or pin without fresh audit.