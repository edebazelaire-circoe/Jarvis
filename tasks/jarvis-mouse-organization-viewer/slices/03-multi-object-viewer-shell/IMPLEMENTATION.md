# S03 implementation — object viewer shell

Implemented in C:/Projects/jarvis/mov3, task/mov-s3. Independent QA/finish review remains with PM; no self-approval.

## Changes and scope
New runtime/control_center_object_viewer.js: native full-viewport dialog, dark Jarvis theme tokens, comparison layouts, image fit/zoom/pan, safe scrolling text, content-provider slots, custom agent/detail slot, bounded local Back history, lazy mounting, timed loading/error/retry and native focus/inert/restore behavior. No scene writes, Core calls, Fullscreen API changes, frame construction or document store. No control_center.py/html/scene-page injection: S05 owns it.

Canonical Escape-only bridge (PM amendment64739e02, read from integration SLICE): native Chromium Escape does not close a dialog when a sandboxed opaque iframe has focus. Minimal shim/protocol/Host extension enables an optional local onEscape callback. Bridge commit: dfec56ed815773c91a2d7ef4fd6d756ad3b25085.

## Final API for S05
```js
const viewer = JarvisObjectViewer.create({
  document, window,
  log: (level, event, data) => { /* bind canonical client journal */ },
  renderEntry: (entry, slot, context) => controller // optional
});
viewer.openObjects(entries, {
  title, layout: 'auto', grid: {rows:3, cols:8}, notice,
  returnFocus: anchorElement, onClose, push: false
});
viewer.openCustom({id, title, mount: (slot, context) => controller}, {push:true});
viewer.setLayout('custom', {rows:3, cols:8});
viewer.back(); viewer.close(); viewer.isOpen(); viewer.snapshot(); viewer.destroy();
```

openObjects/openCustom/setLayout return {ok:true} or {ok:false,code,message}; errors are shown inside the modal and journaled. First opening captures returnFocus/onClose. Subsequent push keeps previous screen mounted (max8); Back disposes current screen, restores old DOM. Native dialog.close also cleans up. destroy is final.

Entries: nonempty, max512 unique IDs. {id,title,kind,...}:
- image: artifactId, optional alt. Only canonical /api/artifacts/{encoded-id}/payload is used; arbitrary supplied URL ignored. Fit scale1, zoom1–8, real wheel/pointer pan and keyboard +/−/0/arrows.
- text: textContent (max500,000 chars), scrolling, explicit empty content.
- provider: mount callback or injected renderEntry; use canonical document/markdown/PrefabHost.
- pdf: provider if supplied; otherwise typed provider_missing fallback + safe canonical Open PDF new-tab link.
- unsupported: typed unsupported_content fallback, optional bounded message and canonical source link when available.

Provider context: {signal,ready,fail,viewer,document,window,log}. Return controller, Promise of controller, or disposer:
```js
{pending:true, dispose(){}, pause(){}, resume(){}}
```
Without pending, fulfilled mount marks ready. With pending, call context.ready/fail. Visible loading: motion/name/live seconds/deadline20s/retry/Close. Failure aborts/disposes; late completion cannot revive closed/retried slot. Close/destroy dispose all mounted controllers. No source contents enter journal.

Layouts: single, horizontal, vertical, quad, row, column, auto, custom, largeLeft, largeTop. Single/pairs/quad/asymmetric pairs paginate with explicit range and Previous/Next. Row/column/auto show all entries with scrolling. Custom supports1–64 rows/cols, max512 cells,6×6 graphical picker with arrow focus and numeric fallback3×8. API initial custom grid uses grid:{rows,cols}.

Layout changes retain same tile/provider DOM and image state. Effective visibility drives pause/resume across BOTH pagination and history. Native text/custom DOM scroll survives Back. Canonical Host.pause deliberately tears down iframe under its LRU policy; Host.resume remounts. Provider internals therefore keep canonical lifecycle limits; shell does not promise iframe state across teardown. S05 should use safe native text/markdown for ordinary documents where available.

## Escape boundary and S05 binding
Viewer document uses native dialog cancel event. Prefab provider host must opt in:
```js
JarvisPrefabHost.createPrefabHost({...existingDeps, onEscape: () => viewer.close()});
```
Exact iframe notice {jv:1,type:'escape'}, no fields. Shim only trusted plain non-repeated Escape after init; removes listener on teardown. Host requires current live ready focused iframe + opaque origin/source; staged/stale/paused/unmounted/unfocused denied;1 notice/second/frame/generation. Ordinary hosts without callback unchanged. No arbitrary keys/text/synthetic DOM keyboard events, no Core/fullscreen write. Callback exception visible in existing host note + logged.

Native dialog is browser TOP LAYER, not z-index rank. Registered explicitly in docs/control-center-shell.md without fictional numeric row/mirror. Global toasts/confirmations stay behind it: keep feedback/actions inside modal. S05 closes existing menus/modal flows and reconciles Settings/Studio/fullscreen exclusivity; actual Fullscreen owner unchanged.

## Validation actually run
Foreground focused checks, main checkout venv Python, cwd mov3:
- pytest --assert=plain --tb=short -q tests/unit/test_object_viewer_js.py tests/unit/test_prefab_escape_bridge.py tests/unit/test_prefab_protocol_js.py tests/unit/test_prefab_shim_js.py tests/unit/test_prefab_host_js.py → **54 passed in13.65s**.
- pytest --assert=plain --tb=short -q tests/unit/test_object_viewer_browser.py -x → **7 passed in47.82s**.
- pytest --assert=plain --tb=short -q tests/unit/test_control_center_shell_layers.py → **11 passed,1 known baseline failure**: existing rail rule control_center_presentation_rail.js #${DOM.hostId} .jvr-play z-index1 lacks registry row. PM independently established baseline; S03 introduces no z-index.
- node --check for viewer and Host, git diff --check → passed.
- Impeccable detector once: node C:/DevTools/skills-lib/impeccable/scripts/detect.mjs --json jarvis/runtime/control_center_object_viewer.js → **[]**, exit0.

Browser uses real isolated Chromium/CDP and aiohttp fixture payload server, canonical profile cleanup. Real clicks/keys/wheel/pan;1/2/4/5/24 entries in BOTH circuit-board/Cosmos; all layout APIs/custom graphical picker; image zoom/pan/fit; document scrolling and text-injection safety; focus/inert/restore; custom detail→artifact→Back preserves DOM/scroll; page visibility pause/resume counters without remount; real canonical PrefabHost and iframe-focused Escape; timeout/retry/fallback; reduced motion;640×400 CSS viewport (equivalent space at200% of1280×800).

Pure bridge tests cover exact message shape, other keys/extra fields/untrusted/modified/repeated keys, before-init and teardown, correct focused live source, spoof/wrong origin, unfocused, staged, old/paused/unmounted frames, rate, absent callback, callback failure visible/logged.

## Visual evidence
Two bounded inspection rounds. First found image contain sizing and narrow tile toolbar clipping; corrected in one batch. Final inspected both five/24-entry desktop captures and200%-equivalent viewport; controls/content remain usable. Current files:
- evidence/circuit-board-5.png
- evidence/circuit-board-24.png
- evidence/cosmos-5.png
- evidence/cosmos-24.png
- evidence/viewer-200-percent.png

All images/documents in this harness are labeled synthetic fixture content. No user artifacts/runtime/data touched.

## Documentation
docs/object-viewer.md is canonical API/content/lifecycle/accessibility contract. docs/control-center-shell.md records native top-layer ownership/exclusivity. docs/ARCHITECTURE.md indexes new seam. docs/prefabs.md records exact optional Escape bridge and guards.

## Limits / next owner
No full suite (S06), live scene integration (S05), real agent read model/actions (S04/S05) or full app integration with Settings/Studio verified here. PDF in-app preview conditional on an existing provider; default is truthful fallback. Independent code/critical bridge/mutation/finish review remains PM/QA work. No nested agents launched per PM machine constraint.
