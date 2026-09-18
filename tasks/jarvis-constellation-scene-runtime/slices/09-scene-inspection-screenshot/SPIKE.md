# Slice 09 — Screenshot spike (report, no production code)

Agent 01, 2026-09-17, tree at `6c4ab42` (query tools committed). Timeboxed. The prototypes live in the
scratchpad only (`s9_spike/`): `s9_spike_host.py` (in-process Core + Control Center on a fresh scratch root,
agent start suppressed, seeded scene), `s9_spike_browser.py` + `s9_spike_capture.js` (own headless Chrome 152,
scratch profile, CDP), `s9_spike_server_render.py` (stdlib renderer), `s9_spike_printwindow.py` (ctypes
`PrintWindow`). Raw numbers: `s9_spike_browser.json`, `s9_spike_server_render.json`, `s9_spike_printwindow.json`;
images `s9_cdp_*`, `s9_canvas_*`, `s9_server_*`, `s9_printwindow_*`. Every process started was killed
(checked by command line: 0 left). The user's Chrome, tabs and live JARVIS were never touched.

Question to answer (acceptance): *the brain can verify an overlap visually on demand*, with the screenshot
exceptional (Decision 16), never on the normal control path, bounded, loopback only.

## What part 1 already gives without any image

`scene_query near={object_id, radius: 0}` lists every **committed** box that touches or overlaps an object,
nearest first, with an edge-to-edge `distance` column (0 = overlap/contact); `scene_get` gives the exact
geometry, layer and order of each. For "does the note overlap the window?" this is exact, cheap (one read, a
few hundred bytes) and needs no browser. What it cannot see: how the page *draws* it (compact shapes, capsule
clamp, fixed-size points, runtime signals stacked with their star, clipping at the viewer's real window size)
and objects not yet committed by the resolver. In the seeded scenes the resolver had committed **every**
visible object within 4 s of the page opening (`unplaced_after_4s: 0`, normal and 493-object dense scene), so
the second gap is transient.

## Scene used

Normal: 7 runtime stars (unplaced, placed by the page resolver; one failed with its live signal), a research
capsule explaining a star, windows A (layer 220) and B (layer 240) overlapping, a window partly beyond the right
frame edge, a pinned user window, a hidden window. Dense: the same plus 480 brain objects (points, capsules,
windows) at random committed positions (493 drawn nodes).

## Options compared

### (a) Browser-side capture by the page leader, requested through the transport

Two in-page techniques were prototyped (CDP only as a reference, it does not exist in production).

**(a1) Deterministic canvas render of the scene view model** (`s9Canvas`): fetch `/api/scene`, run the
page's own `JarvisSceneLayout.resolveLayout` + `viewport(innerWidth, innerHeight)` + `viewModel`, draw edges then
nodes in `stack` order on an `OffscreenCanvas` (tone palette of the page CSS, shape = `node.shape`, i.e. after
compaction, box = `node.box` after `drawnBox`), `convertToBlob('image/png')`. No dependency.

**(a2) SVG `foreignObject` serialisation of `#sceneLayer`** (`s9ForeignObject`): all same-origin CSS rules +
cloned layer in an SVG image drawn on a canvas.

| Measure (headless Chrome 152, DPR 1) | CDP reference | (a1) canvas | (a2) foreignObject |
| --- | --- | --- | --- |
| normal 1920×1080: time | 121–149 ms | 22–27 ms warm (113 ms first: draw 41 + encode 72) | serialise 4 ms + load 14–19 ms, then **`SecurityError: Tainted canvases may not be exported`** |
| normal 1920×1080: PNG | 90.9 KB | 120.6 KB | — (SVG 101.6 KB, cannot become a PNG in the page) |
| normal 1280×720 | 71–90 ms, 72.1 KB | 17 ms, 89.6 KB | tainted |
| dense (493 nodes) 1920×1080 | 242–293 ms, 306 KB | 64–125 ms (model 1.8, draw 4.5–36, encode 58–87), **678 KB** | tainted (SVG 363 KB) |

Fidelity observed (compare `s9_cdp_normal_1920x1080.png` with `s9_canvas_normal_1920x1080.png`): every box
lands on the same pixels as the DOM (same code path), B is drawn over A, the off-frame window is cut at the same
place, resolver placements of the stars are identical, the hidden window is absent. Not reproduced: the dock,
topbar and chips (by design: scene only), fonts and inner window layout are approximations, hover-only labels
were drawn always (prototype choice), the Omega face canvas is absent.

- **Fidelity:** what the leader page draws, at the leader's real viewport: resolver placements (even
  uncommitted), compaction, capsule clamp, signal stacking, clipping. Not pixel-identical text.
- **Privacy:** scene content only (titles, summaries, items of windows) — the same data the brain can already
  read with `scene_get`. No other application, no dock text, no face.
- **Dependencies:** none (Canvas 2D / `OffscreenCanvas`, already in every supported Chrome).
- **Failure modes:** no Control Center page open; page hidden or occluded (Slice 05: hidden tabs do no network,
  a hidden tab declines leadership) → no leader to answer; leader hung (Slice 05 residual); gate off; upload
  refused or too large; Core restart mid-request. All must end in a clear tool error within a deadline.
- **Latency:** render 17–125 ms + base64 + two loopback hops; delivery depends on the channel (a leader already
  holds a patches long-poll, so a woken long-poll answers in ms). Estimate < 0.5 s with a visible leader;
  bounded by a tool deadline (proposal 5 s).
- **Size bounds:** PNG 90–680 KB at 1280×720–1920×1080. Proposal: render at most 1280×720 (scaled from the
  leader viewport, aspect kept) — about 1 230 image tokens for the model, ≤ ~400 KB even dense; hard cap 2 MiB on
  the upload body.
- **Security:** request only from the display MCP (Core bearer token), upload only from the Control Center page
  (origin guard like every POST, strict bounded body, PNG signature and IHDR size checked), loopback only; files
  under `runtime/scene-captures/`, keep last N (proposal 5) and delete older, never outside `runtime/`; journal
  identifiers, size and timings only.
- **Implementation cost:** medium-high. Page renderer (~150 lines, reuse `viewModel`), a capture request channel
  (Core → Control Center → page leader), an upload route and a Core/CC hand-back, deadline and error paths,
  node + integration + browser tests. Must not add a second long-poll (Issue 04, connection budget): the request
  has to ride the existing scene channel.
- **Test strategy:** node test of the renderer on fixture view models (shape/box/stack pixels sampled at known
  points); integration test with a fake leader answering/not answering/oversized/garbage; headless-Chrome
  runtime check comparing sampled pixels against DOM rects; live brain turn "vérifie que la note ne chevauche
  pas la fenêtre".
- **Windows reliability:** good while a visible Control Center window exists (no OS API involved); zero when the
  window is minimised or fully occluded (Chrome marks the page hidden, the scene stops polling by design).

(a2) is **ruled out**: Chrome taints a canvas that drew an SVG `foreignObject`, so the page cannot export it; the
SVG itself is not an image the model can read and rasterising it elsewhere needs a browser anyway.

### (b) OS window capture of the Control Center browser window

Prototype: own **non-headless** Chrome (scratch profile, `--app` window) placed *outside every monitor* (checked
with `MonitorFromWindow` before any capture, aborted otherwise), captured with `PrintWindow(hwnd, …,
PW_RENDERFULLCONTENT)` + `GetDIBits` via `ctypes` (no dependency). Never a screen DC capture.

| Case | Result |
| --- | --- |
| window off-screen, 6 s after load | 31 ms, 1600×900 bitmap, **blank page** (title bar only, 9 distinct colours sampled) — Chrome's native occlusion tracking never painted it |
| minimised | 19 ms, 199×34, **blank** |
| restored (still off-monitor) | 29 ms, 20 KB, page chrome painted but scene shows **« Scène · chargement… »**: the page was hidden, so by design it had fetched nothing |
| DPI | process DPI-aware at 125 %: bitmap 1600×900 with the 1280×720 content in a corner (scaling must be handled) |

- **Fidelity:** exactly what the window shows, including dock, chrome, face — only when the window is visible
  and uncovered.
- **Privacy:** `PrintWindow` limits it to one window, but finding the right window is heuristic (title/class of
  any Chrome window, including the user's own browser with other tabs); the easy alternative (`mss`, PIL
  `ImageGrab`, BitBlt of the screen) captures **whatever covers the window: other applications**. Highest
  exposure of all options.
- **Dependencies:** none with `ctypes` `PrintWindow`; `mss` or `winsdk`/Windows Graphics Capture otherwise (WGC
  needs WinRT bindings and shows a capture border unless the app opts out).
- **Failure modes:** minimised, occluded, off-screen, other virtual desktop, locked session (all blank or stale,
  observed); wrong window picked; DPI scaling; Chrome GPU compositing changes; the user's normal Chrome tab
  (not an `--app` window) mixes the scene with their other browsing.
- **Latency / size:** 20–31 ms capture, 10–20 KB PNG here (mostly blank); a real 1920×1080 content capture is
  in the CDP range (~90–300 KB).
- **Security:** a Core/CC process reading pixels of desktop windows is a new, broad capability.
- **Implementation cost:** low code, high uncertainty; Windows-only.
- **Test strategy:** hard to automate without showing windows on the user's desktop.
- **Windows reliability:** **poor** — fails in exactly the situations where the user is not looking at the
  Control Center.

### (c) The brain's `--chrome` screenshot tool (claude-in-chrome)

Verified without touching the user's browser:

- The brain CLI (2.1.274) loads the `claude-in-chrome` MCP server (`system/init.mcp_servers`: `connected`,
  22 `mcp__claude-in-chrome__*` tools including `computer` with `screenshot`/`zoom`, `tabs_create_mcp`,
  `navigate`) — observed in the Slice 09 live run trace.
- `list_connected_browsers` returns `[]`: **no Chrome extension is linked** in this environment, so every call
  would fail today.
- From the tool contracts: `computer.screenshot` needs a `tabId` **inside the MCP tab group**; the brain must
  first `tabs_context_mcp` (creates a new window/tab group when empty) and `tabs_create_mcp` + `navigate` to the
  Control Center URL. It cannot target the user's already open Control Center tab, and it opens a window in the
  user's own Chrome session (visible, focus-stealing), with per-site permission prompts. Before any action the
  extension flow asks the user to choose a browser.

- **Fidelity:** real page pixels of *its own* new tab (a second Control Center page: a follower, other viewport
  than the user's).
- **Privacy:** operates the user's real browser profile (cookies, other tabs in reach of the same tool set).
- **Failure modes:** extension not connected (current state), permission prompts, browser choice question,
  focus stealing, second page adds a scene follower; not controllable from JARVIS code.
- **Latency:** several tool round trips (context, create, navigate, wait, screenshot) → seconds; image returned
  to the model directly.
- **Security:** outside JARVIS's loopback boundary and journal; decided by the extension, not by Core.
- **Implementation cost:** zero code, but a prompt rule that sends the brain into the user's browser.
- **Windows reliability:** unverifiable here (not connected); disturbing by construction.
- **Verdict:** not suitable as the product path; keep it available for ad-hoc debugging by a human request only.

### (d) Server-side deterministic render of the committed geometry

Prototype: stdlib Python only — boxes from the Core snapshot in `(layer, order)` order, relations, safe area,
overlap rectangles in red, an index number per box (3×5 bitmap digits) and a JSON legend (index → id, overlap
pairs, unplaced ids); SVG text and a PNG written with `zlib` + `struct`.

| Scene | Render | PNG encode | PNG | SVG | Legend |
| --- | --- | --- | --- | --- | --- |
| normal 1920×1080 | 6.5 ms | 29.5 ms | 15.7 KB | 3.4 KB | 408 B, 2 overlap pairs |
| normal 1280×720 | 4.9 ms | 12.7 ms | 8.8 KB | 3.4 KB | |
| dense 1920×1080 | 454 ms (O(n²) overlaps + SVG strings) | 40.5 ms | 92.6 KB | 1.08 MB | 14.8 KB, 9 599 overlap pairs |
| dense 1280×720 | 331 ms | 18.7 ms | 46.4 KB | 1.07 MB | |

Fidelity (`s9_server_normal_1920x1080.png`): exact committed boxes and the A/B overlap, but **stored** boxes,
not drawn shapes: a star is its 6×6 box (the page draws a fixed-radius dot), a star and its signal are reported
overlapping (the page draws them apart visually), no compaction/clamp, no clipping at a real viewport (the
server does not know the viewer's window size), unplaced objects missing (listed instead). No text.

- **Privacy:** none beyond what `scene_get` returns (geometry and ids).
- **Dependencies:** none (stdlib); Pillow would add text but is a new dependency.
- **Failure modes:** only Core reachable; always works, with or without a page.
- **Latency / size:** 20–500 ms, 9–93 KB PNG.
- **Security:** read-only, Core token, file under `runtime/` if stored.
- **Implementation cost:** low (Python only, unit-testable byte for byte).
- **Windows reliability:** excellent (no OS or browser involvement).
- **Limit that matters:** it is a picture of the same data `scene_query near` already returns exactly; to show
  what the user sees it would have to re-implement `drawnBox`/`compactShape`/signal stacking and guess a
  viewport in Python (drift from the JS renderer).

## Summary

| Option | Fidelity to what the user sees | Privacy | Deps | Works when | Latency | PNG 1920×1080 | Cost | Windows reliability |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| (a1) page canvas render via transport | high (leader viewport, compaction, stacking, clipping, uncommitted placements) | scene only | none | a visible CC page exists | ~0.1–0.5 s | 121 KB normal / 678 KB dense (≤ ~400 KB at 1280×720 cap) | medium-high | good while visible |
| (a2) foreignObject | would be highest | scene only | none | — | — | **impossible: tainted canvas** | — | — |
| (b) OS window capture | exact when visible and uncovered | **high** (other windows/apps) | ctypes / mss / WinRT | window visible and uncovered | 20–30 ms + encode | 90–300 KB | low code, high risk | **poor** (blank off-screen/minimised, observed) |
| (c) brain `--chrome` | its own new tab, not the user's | user's real browser | extension | extension linked (not today) | seconds | — | zero code | unverifiable, disturbing |
| (d) server render | committed boxes only | none | none | always | 20–500 ms | 16 KB normal / 93 KB dense | low | excellent |

## Recommendation

1. **Normal path for overlaps stays structured**: `scene_query near radius 0` + `scene_get` (part 1). The prompt
   and tool description can say so; no image needed for "is it overlapping?".
2. **Screenshot = (a1)**, the leader page renders its own view model to a PNG on request. It is the only
   option that shows render-side truth (compaction, clamp, stacking, the viewer's clipping, uncommitted
   placements) without privacy exposure beyond scene content and without a dependency. Tool
   `scene_screenshot` explicitly described as exceptional ("vérification visuelle ponctuelle ; pour savoir si
   deux objets se chevauchent, scene_query near suffit"), 1280×720 max, 5 s deadline, clear refusal when no
   visible Control Center page answers (« aucune page du Control Center visible : utilise scene_query near »).
3. **Reject (a2), (b), (c)** for the product: tainted canvas; unreliable and privacy-heavy on Windows; operates
   the user's own browser and is not connected.
4. (d) is not needed as a fallback: when no page is visible, nobody is looking at the scene, and the structured
   answer is exact for committed geometry. Keep it as a cheap alternative only if agent 0 prefers "always works"
   over "what the user sees".

## Decisions needed from agent 0

1. **Choice:** (a1) as recommended, or (d) (cheaper, always available, committed geometry only).
2. **Channel for (a1):** proposal — display MCP → Core `POST /v1/scene/captures` (waits ≤ 5 s) → Core wakes the
   scene patches long-poll with a `capture` request id → Control Center relays it in `/api/scene/patches` → page
   leader renders → `POST /api/scene/captures/<id>` (Control Center, origin guard, ≤ 2 MiB, PNG checked) → Core
   stores `runtime/scene-captures/<id>.png` and answers the waiting call. No new long-poll (Issue 04). Or: the
   display MCP talks to the Control Center directly (it only knows Core today).
3. **Return form:** MCP image content (FastMCP `Image`) and/or the file path. Whether the brain CLI forwards MCP
   image content to the model was **not verified** in this spike (no model spend); first implementation step.
4. **Bounds and retention:** 1280×720 max render, 2 MiB upload cap, keep last 5 files (or delete after the tool
   returns), journal ids/sizes/timings only; SECURITY §13 wording (screen content exposure = scene content).
5. **Who may trigger:** display MCP only (brain), not a page or user route in V1?
6. **Which page answers when several are visible:** the Web Locks leader only (its viewport) — acceptable?
