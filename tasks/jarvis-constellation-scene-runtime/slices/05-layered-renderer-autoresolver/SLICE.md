# Slice 05 — Layered renderer & AutoResolver

## Goal
Render the persistent scene in the Control Center as strict-2D layers: ambient canvas beneath, SVG relations, absolutely positioned interactive DOM nodes (Decision 19), with a constrained browser-side AutoResolver (Decisions 8–10).

## Context
Audit facts: vanilla JS, no build; JS files injected into `control_center.html` at text markers (`control_center.py:474-485`), each with a pure part exported via `module.exports` for node tests and a browser IIFE. Themes: `circuit-board` (ai-visualizer iframe, default) and `omega` (`OmegaRenderer` full-screen canvas z-index 0). Existing z-index usage: banner 35, bgpills 40, Omega panel 42/topbar 45/banner 48/dock 50, overlay 60, toasts 70, bgpop 75, ctxmenu 80, Barehands 2147483000. No SVG overlay, no drag/resize today. Visual direction doc is the aesthetic North Star (not in this repo; Human must provide it if needed), overridden on completion-fade.

## Canonical Concepts
- Scene layer container between ambient face and chrome (above face/canvas, below dock/panels/pills/modal/ctxmenu), theme-independent. Internal scene layer ints map to stacking inside the container only; never exceed chrome.
- Colour token = `category`; `exec_state` = halo/ring/pulse/badge. Completed objects remain rendered (no fade-out).
- Representations point/capsule/window share one DOM identity keyed by `object_id`.
- AutoResolver (pure JS): priority user pins > explicit brain/user placement > resolver; only places unplaced objects or nudges `placed_by=resolver` ones; overlap is allowed across different layers and for explicitly placed objects; deterministic output for the same input. Resolver results are render-local; they are persisted only when committed back via a command (`placed_by=resolver`) — PM decision to keep positions stable across reloads.
- Honour `prefers-reduced-motion`.

PM amendment (Slice 01 QA): payload text may contain DEL, C1, bidi overrides (U+202E), zero-width and U+2028 characters. Render only via `textContent` (never `innerHTML` for scene payload) and neutralise bidi override/isolate controls so summaries cannot spoof their displayed content.

PM amendment (Slice 03 QA): browsers allow ~6 HTTP/1.1 connections per host:port and each tab's 25 s scene long-poll holds one alongside the 1 s `/api/status`/`/api/work` polls. The page loop must: run a single scene long-poll per tab, pause it when `document.visibilityState` is hidden (resume with a snapshot/patch catch-up), honour the Control Center long-poll cap response (`retry`), and back off on errors. Validate with several tabs open. Use `window.JarvisSceneClient` (already injected) rather than re-implementing patch application. Runtime validation must never start the Control Center through the launcher (`webbrowser.open` opens a tab in the user's browser): drive `ControlCenter` in-process or use a dedicated test tab opened and closed by the validator.

PM amendment (Slice 04 QA): `parent_of` cycles can exist — layout/traversal must tolerate them. A retired signal keeps its old category; decide liveness only with `is_live_signal` semantics (an attention is live iff its `explains` relation with `relation_id == from_id` exists). `process_stopped` interruptions produce one signal per running sub-agent at each brain CLI stop — style them as low-urgency.

PM amendment (Slice 06 live run): no scene coordinate convention exists — asked "top left", the brain chose geometry (-80,-80,40x15). This Slice must define and document the scene coordinate frame (origin, axis directions, units, visible viewport extent and how it maps to the browser at any window size), render accordingly, and expose the frame to the brain: add it to the `scene_inspect` header/legend in `jarvis/runtime/display_mcp.py` and one line of guidance in the display prompt. Keep brain-given geometry authoritative (Decision 10); the resolver only places unplaced objects.

## Scope
### In Scope
`control_center_scene.js` renderer + resolver, CSS, marker injection, feature flag gate (render only if enabled, see 11), node tests for resolver.
### Out of Scope
Pointer interactions beyond hover (08), screenshot (09).

## Dependencies
03.

## Implementation Steps
1. Container + layer mapping. 2. SVG relations. 3. DOM nodes per representation. 4. Resolver + tests. 5. Live check in browser with a seeded scene.

## Files Likely Touched
`jarvis/runtime/control_center_scene.js`, `jarvis/runtime/control_center.html`, `jarvis/runtime/control_center.py` (marker), tests.

## Architecture Constraints
No framework/build migration; no 3D/parallax; legacy panels/pills/Barehands keep working and stay above the scene.

## Automated Validation
Node resolver tests; `tests/unit/test_control_center_*` green; runtime browser validation with screenshots in both themes.

## Acceptance Criteria
Pins never moved by resolver; explicit overlap preserved; reload renders identical layout; chrome remains clickable.

## Documentation Updates
ARCHITECTURE.md Control Center section; layer registry documented.

## Handoff Notes
Skills: `/caveman`, `/coding-guideline`, `/impeccable`; route to a Claude agent. QA: qa-verification + code-review + runtime-validation.
