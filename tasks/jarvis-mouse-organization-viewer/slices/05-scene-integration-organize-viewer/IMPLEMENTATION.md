# S05 implementation

Branch `task/mov-s5`, isolated worktree `C:/Projects/jarvis/mov5`.
Predecessors integrated: S01/S02/S04 plus actual S03 commits
`dfec56ed815773c91a2d7ef4fd6d756ad3b25085` and
`6f545abe755f292cff887dc54e4596f1c2b71d94` (local cherry-picks
`392df693`, `c5b772d5`). No production fixture fallback.

## Final modules and contracts

- `JarvisSceneOrganize` (`control_center_scene_organize.js`): pure
  `plan(members, action, {rows,cols,scale,viewport,area})`, with members
  `{id,representation,box:{x,y,w,h}}` in **drawn scene units**; returns same-shaped
  target members. Actions: `row,column,grid,custom,left,center,right,top,middle,
  bottom,distributeX,distributeY,width,height,size`. Existing spatial ordering,
  stable bounding centre, three-unit packing gap, complete-area clamp/refusal.
  Nonresizable mixed sizes are refused. `command([{id,before,after}],pin)`
  produces the real S01 `layout_selection` with every `expected_geometry`.
  `checkBudget` verifies forward/reverse UTF-8 wire size, conservatively including
  Python canonical float overhead and actor; no chunked or partial organization.
- `createHistory({now?,limit?,ttlMs?})` exposes `record,size,clear,take`.
  Defaults: 20 entries, 120 seconds. Entry
  `{board_id,scene_id,epoch,targets:[{id,representation,before,after}]}`.
  `take(state,boardId)` consumes the latest entry and refuses wrong context,
  changed representation/visibility/geometry. Core exact compare remains final
  authority. Undo changes geometry only; current pin and nongeometry remain.
- Scene page composes the existing hold desk: `takeHold` → `hold.start` → pure
  plan → `desk.to` → `hold.place` at current canonical orbit turn → one command.
  New `desk.finish(handle)` releases a successfully converted hold without
  triggering per-member writes. This is an extension of the shared engine.
  Organization and resize use compared atomic writes with pin true. Legacy
  movement keeps its existing semantics and is outside the undo ring.
- Group movement correction: `createHoldDesk.drop` invokes optional
  `commitMany(targets,kind)` once with all placed `{id,box,before,representation}`
  members, before release. No delta sends nothing; conversion/callback throws
  still release every hold. Production injects `commitManyGeometry`, composing
  the same `commitAtomicGeometry` path with pin true and no undo record. Single
  moves keep their previous callback. A prior interpretation of the obsolete
  inline-source group assertion as merely stale was incomplete: the shared
  desk really sent N writes. PM and independent runtime QA confirmed the
  regression, and S05 now repairs the shared commit seam. Browser cases cover
  three targets, fixed/orbit, refusal rollback and exactly one revision/write.
- A context change (active Board, scene ID, epoch) clears the ring and aborts
  the pending wait. A late success cannot record history for the new context;
  its old optimistic tokens are rolled back. All refusal/error exits remove
  their pending layers. Core may already have admitted an aborted request;
  the UI says **annuler l’attente**, never promises server rollback.
- `JarvisSceneViewer.create({document,window,layout,scene,fetchJson,sendJson,
  log,appendBlocks,cancelDeadlineMs,focusElement,beforeOpen,onClose?})` exposes
  `open(ids,anchorId),grid(ids,apply,anchorId),canView,isOpen,close,snapshot`.
  It composes actual S03 shell, S04 reader, Artifact metadata, markdown blocks
  and canonical PrefabHost preview. The host injects modules before scene page.
  No new endpoint, status owner, bus, provider renderer or geometry engine.
- Enter, double-click and Open/View dispatch identically from S02's bubbling
  `jarvis:scene-open` event `{objectId,ids,source}`. Agent/job anchor opens alone;
  document anchor opens compatible selected window/artifact members and states
  the skipped count. Modal keys stay inside the dialog, respecting a provider's
  `defaultPrevented`; Escape closes via S03. Selection is retained and anchor
  focus restored. Existing fullscreen/other modal returns a readable refusal.
- Actual registry text preview requests `text_chars=16000`, verifies artifact
  identity and states truncation. Image uses canonical payload/native zoom/pan.
  PDF has S03's explicit source-link fallback. Plain summary/items use existing
  markdown blocks. Prefab preview uses the existing isolated host; generic
  `onEscape` and canonical Remotion `onKey(id,'Escape')` both close. Remotion
  additionally requires its active iframe within that provider slot. Pause can
  reconstruct an iframe according to existing host policy; no opaque iframe
  state-preservation claim.

## Agent template and chat

Real S04 reader, five-second refresh only while visible; history pause cancels
reads/timer and resume reloads. A 500 ms display clock uses existing taskElapsed
and wait counters. Identical content is retained, preserving text selection,
focus and scroll. Actual changed sections restore focused artifact and scroll;
reader error clears old timing as well as old model content.

Public DOM hooks: `.scv-agent[data-status]`, `[data-agent-status]`,
`[data-agent-action=stop|ask|retry]`, `[data-agent-artifact=objectId]`.
Stop sends S04's descriptor to the canonical cancellation route; ten-second
request deadline, actual `stopOutcome`, bounded Core-terminal confirmation using
configured job cancellation deadline. CLI Stop remains explained/disabled.
Artifact navigation has a ten-second deadline and real S03 push/back history.
All wait/error/action feedback lives inside the native top-layer overlay.

`JarvisChat.prefill({text,target?,signal?})` returns
`{ok:true,conversation_id}` or `{ok:false,code,message}`. It opens the existing
current Board chat, appends after an existing draft with two newlines, retains
attachments and persists through the normal draft owner. It rejects changed
Board, abort, unavailable chat or combined 8,192-character overflow without
overwriting the draft. Ask closes viewer only after success, then focuses chat.
No automatic turn, Voice channel switch or provider/prompt modification.

Menus use existing `showMenu`: `[data-act=organize]`, `layout-align`,
`layout-distribute`, `layout-size`, `layout:<action>`, `geometry-undo`.
Custom `.scv-grid-form` has numeric inputs `rows`,`cols`, 6×6 graphical buttons
`[data-rows][data-cols]` and `[data-organize-apply]`. 3×8 is supported.
Geometry wait has `[data-geometry-cancel]`. `JarvisScene.inspect()` exposes
read-only `viewer`, `undo` count and `geometryBusy` alongside existing diagnostics.

## Validation and root causes

Focused tests only, main checkout interpreter, own fixture/sandbox data. No
user runtime modified. Browser tests run real Chromium input against the actual
served page and final production modules; fetch fixture is explicit test-only.
Planner output also goes through the actual Python scene reducer. The separate
independent QA campaign exercises actual Core/SQLite/HTTP writes and live agent
reads/cancel; it is not replaced by these fixtures.

- `test_scene_organize_js.py`: every action deterministic, canonical atomic
  reducer, 3×8/size/area refusal, actual Python wire budget, expiry/stale/Board.
- `test_scene_convergence_browser.py`: atomic organization/undo and resize/undo,
  pin preservation, every organization menu action with orbit enabled, custom
  numeric grid, compatible mixed viewer paths, focus/selection/geometry, desktop
  and narrow screenshots.
- `test_chat_prefill_browser.py`: append existing draft, overflow, abort, no
  turn or Voice write in actual canonical chat UI.
- `test_scene_viewer_provider_browser.py`: actual scene adapter + S03 shell +
  PrefabHost + Remotion protocol parser, canonical trusted-shell transport
  fixture; unfocused same-frame key ignored and focused real Escape closes.
  This validates wiring, not a React/Remotion rendering run.
- S02 mouse browser coverage adapted from legacy `set_geometry` expectation to
  one-target compared atomic resize. Existing gesture shield fixture now supplies
  the geometry-busy guard. Input harness Escape uses native keyDown.

An integration defect found by the real page tests was the global incumbent
`ui_close` shortcut preventing native dialog cancel and closing a background
panel instead. Local modal key propagation boundary fixes it; no focus-delay
workaround or second fullscreen manager was added. Polling previously rebuilt
all agent sections even unchanged; content stamping/focus restore fixes that.

Impeccable detector on the four changed/new UI JS targets: `[]`. Syntax checks
and `git diff --check` clean. Final focused test counts and screenshot inspection
are recorded below before the implementation commit.

No full suite or authoritative approval in this implementation report. PM owns
independent QA, acceptance and final release gate.

### Focused results

- Pure planner + shared hold desk + gesture shields + canonical chat UI +
  public agent projection: **80 passed, 26.25 s**.
- Added group atomic seam/release-on-throw + corrected real page wiring +
  existing group math/translation + gesture shield: **23 passed, 8.61 s**.
- Convergence, chat prefill, Remotion provider and eight-handle/Shift/input
  Chromium batch: **10 passed, 152.47 s**, before the added group regression
  correction. This includes all fourteen organization menu actions with orbit.
- Final custom graphical picker + invalid capacity inline feedback + numeric
  3×8, keyboard/focus/native viewer at 1920×1080 and 600×800, plus brain-window
  equal-height stability: **3 passed** in the final six-case run. The other
  three cases in that run failed before any product interaction because the
  test used capsule `.sc-title` on a full window; corrected to `.sc-wtitle`,
  then reran only those three group cases.
- Corrected group selector: fixed and refused-orbit **2 passed**; applied-orbit
  initially raced the first node render under workstation memory pressure.
  A bounded readiness predicate was added to the browser actions; the isolated
  applied-orbit rerun **1 passed, 15.68 s**. All three final group outcomes are
  now verified. No further product changes followed these checks.

Explicit atomic window targets enter the existing `userSized` set before any
optimistic render. This prevents late `fitBrainWindows` set_geometry writes
from undoing requested dimensions or adding hidden extra mutations. The final
brain-window test observes initially different auto-fit heights, then one batch,
equal retained heights, and no late per-object write over 1.8 seconds.

Desktop/mobile PNGs in `evidence/` were visually inspected: viewport-contained
header/close/layout controls, readable skip notice, independently bounded panes,
document padding. One bounded visual adjustment added normal document padding;
the final capture pass confirms it. Detector remains `[]`.

### S05 rework: closed-chat Board scope freshness

Independent review found that retaining a non-null conversation ID while chat
was closed bypassed the asynchronous channel refresh on reopen. Ask could append
to the previous Board's draft. Canonical `prefill` now settles the shared state
read and performs a fresh `/api/chat/state` read before editing. It verifies the
returned Board and conversation against the current Board/model and ignores
cancelled reads; reads are coalesced so background polling cannot overtake or
overlap the foreground freshness check. The existing rescope/draft owner loads
the correct draft. No send, Voice switch or attachment semantics changed.

The real-browser regression switches A→B→A with chat closed, explicitly observes
the old non-null conversation ID, delays channel responses, preserves both saved
drafts, cancels during the first scope read, then appends only to each fresh
conversation. No turn or Voice-disable POST occurs. Replacing only `prefill`
temporarily with the exact previous-commit function kills this regression
(old function returns success before cancellation settles). Product bytes were
restored exactly in `finally`; no temporary fixture reaches production.

Final focused rework validation count is recorded below before its separate
commit. Earlier S05 implementation remains `80607352`.

Rework checks: `test_chat_prefill_browser.py` (existing draft/overflow/abort +
closed two-Board delayed-read/cancellation regression) and
`test_control_center_chat_ui.py`: **11 passed, 34.01 s**. Previous prefill
replacement: **1 failed, 15.53 s**, product restored exactly. `node --check`
and `git diff --check` pass. No full suite or user runtime touched.
