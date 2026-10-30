# Independent PM UI/code/runtime review — S03

Reviewed integrated c3b9ea7d+39f05040 (original dfec56ed+6f545abe): viewer module, canonical Escape bridge, provider lifecycle, tests/docs and visual evidence. Applied qa-verification, code-review, runtime-validation and scoped impeccable audit.

Independent execution in mov: main venv Python -m pytest --assert=plain --tb=short -q tests/unit/test_object_viewer_js.py tests/unit/test_prefab_escape_bridge.py tests/unit/test_object_viewer_browser.py →15 passed in52.28s. Real Chromium scenarios include focus/inert/restore, actual opaque prefab Escape, image wheel/pan, document scrolling/history, provider visibility lifecycle, custom grid, fallback/loading/error and small viewport. Detector independently returns [] (exit0); git diff --check clean.

Inspected cosmos-5.png and viewer-200-percent.png. Dark spacious comparison surface, readable header/actions, contained images and separately scrollable text. Small viewport keeps Close/layout/zoom controls reachable with deliberate content scrolling. No scene or Fullscreen mutation path in shell.

No blocking finding in UI/code reviewed. Native dialog owns top-layer modality; canonical Host owns opaque frame creation. Escape message exact/fieldless, trusted plain Escape shim, ready/current/focused frame/source checks, rate bound and optional local callback only. Independent adversarial/mutation bridge QA still pending from a different implementer; PM UI acceptance is conditional on it. PDF default is explicit provider_missing/new-tab fallback, not an in-app PDF preview claim. Host pause/LRU may reset opaque provider internals; native DOM scroll/history preserved.

Scoped technical health (not a full WCAG certification):

| Dimension | Score/4 | Evidence/limit |
|---|---|---|
| Accessibility |3|Native modal/focus, keyboard, labels and reduced motion exercised; no screen-reader hardware audit|
| Performance |3|Lazy mounts, pause/resume on effective visibility, no new renderer/transport; no measured long-session memory profile|
| Responsive |3|Both themes and small/200%-equivalent captures; some desktop controls36px below touch44px preference|
| Theming |3|Incumbent tokens, explicitly pinned near-black surface, both current dark themes|
| Integrity |4|Detector clear, explicit data/provider seams and bounded async lifecycle|
| Total |16/20|Good; minor polish only|

Polish batch for release: layout presets are currently a labeled native text select; UI brief requests visual representations as well. Add a compact selected-layout schematic or equivalent visual aid without expanding toolbar complexity. Touch sizing is non-blocking for this mouse/keyboard task. Do not reopen broad design work.

