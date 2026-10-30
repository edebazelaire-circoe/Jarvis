# S06 narrow convergence implementation

Worktree `C:/Projects/jarvis/mov5`; merged the accepted PM integration branch
before editing. S01–S05 implementation and independent acceptance are already
integrated. This report covers only the delegated convergence changes. PM owns
the complete release gate and final approval; no full suite or model run here.

## Changes

- I-001: source conformance reuses production
  `jarvis.domain.remotion_import.strip_comments` through shared test helper
  `tests/fakes/javascript_source.py`. Stdlib HTMLParser selects inline scripts
  and event handlers so HTML prose/comments do not masquerade as JavaScript.
  Compact forbidden-call matches replace giant raw-HTML assertion failures.
  Actual alert/confirm/prompt calls, window/globalThis/self forms, whitespace
  and comment-separated calls remain detected. Ordinary methods and explanatory
  comments remain allowed. This is static conformance, not a security parser.
- Removed exactly the resolved group-drop node from `tests/known_failures.json`.
  S05 independent runtime QA already verifies actual one-command/one-revision
  group drops. Current canonical page-binding docs now name shared desk
  `commitMany` and compared `layout_selection`; historical September translation
  notes and current Core/MCP translation semantics are distinguished.
- S03 queued visual polish: existing native layout selector now has a 54×34 px
  decorative schematic based on the existing current layout plan. At most 4×6
  cells are sampled, exact rows/columns appear in its tooltip, asymmetric pairs
  retain their 2:1 proportions. No new action, focus stop, API, layout/state
  manager, provider lifecycle or geometry write. Ten layouts retain existing
  content DOM. No redesign.
- Trivial PM-requested copy: only a bare `HTTP 404` degraded-source message is
  rendered as a missing public source explanation. Public projection and
  diagnostic logs retain the original facts; no status or mission inference.

## Focused evidence

Main checkout interpreter; foreground sequential checks, isolated browser
fixture only. No user runtime, database or model interaction.

`test_javascript_source_guard.py`, the formerly failing served-page source
test, `test_control_center_shell_layers.py`, `test_scene_group_drag_js.py`,
`test_object_viewer_js.py`: **31 passed, 15.76 s** before the two additional
globalThis/self guard cases; final guard count is recorded below.

Final expanded source guard + served-page check: **10 passed, 6.07 s**.

New focused Chromium selected-layout test: **1 passed, 9.17 s**. It checks all
ten preset schematics, bounded/decorative nodes, 2:1 asymmetry, unchanged content
DOM, narrow fit, Escape and original focus return. Desktop 1280×800 and narrow
600×800 PNGs in `evidence/` were inspected together: native selector, selected
schematic and pagination fit; content remains the primary surface. No further
visual edits followed inspection.

`node --check` for both changed UI modules and `git diff --check` pass.
Impeccable detector on those modules returns `[]`. No new blocker found.
The root PM should begin the canonical release gate only after this commit;
remaining full-suite/acceptance work is deliberately not claimed complete here.
