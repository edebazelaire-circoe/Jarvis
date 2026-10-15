# 04 - Testing and quality plan

## Global gates

For every implementation slice:

- `qa-verification` is mandatory.
- `code-review` is mandatory for code.
- `runtime-validation` is mandatory for UI/runtime behavior.
- `agent-trace-analysis` is mandatory if an agent/runtime prompt/tool/routing contract is touched.
- `/caveman` and `/coding-guideline` before coding.
- `/impeccable` for frontend slices; use a Claude agent when the host supports the project rule.

Do not validate against the user's live Jarvis process without explicit permission. Use an isolated worktree/runtime/data root.

## Automated test themes

### Wheel core

- closed by default; anchor remains;
- mouse enters hotspot -> open;
- pointer exits with no capture/submenu focus -> close after intended delay;
- keyboard can focus anchor, open wheel, navigate, activate, escape;
- reduced motion path has no dependency on transition completion;
- focus cannot be lost behind the scene;
- wheel never opens from unrelated pointer movement far from left edge.

### Bare Hands wheel input

- leftward hand/two-finger activation event opens the same wheel as Mouse;
- point changes focused wedge without activation;
- pinch activates exactly once;
- no double activation from gesture + synthesized click;
- secondary action maps to one documented event and is keyboard-equivalent.

### Selection arbitration

Pure tests should cover:

- explicit click -> Mouse immediately;
- movement below threshold -> remain Bare Hands;
- movement crossing threshold in time window -> Mouse;
- slow jitter that accumulates over too long a window -> no takeover;
- after Mouse takeover, hand presence does not auto-return;
- explicit Bare Hands selection requests canonical transition;
- failed Bare Hands activation leaves UI truthful and reports failure;
- repeated Mouse events after takeover do not spam transitions/logs.

### Capture migration

Re-run and extend existing capture rail tests rather than replace them.

- Audio start/stop uses canonical status;
- Video start/stop uses canonical status;
- Screenshot one-shot success/failure;
- concurrent Audio + Video states render independently;
- status lost -> unknown, no false active/inactive paint;
- previously known active capture still exposes stop during status loss per current privacy rule;
- duration derives from Core timestamps, not click time;
- stale poll cannot overwrite post-write fresh status;
- reload/new tab projects active capture correctly;
- long/secondary options list only supported sources/targets.

### Screenshot preview

- appears only after successful screenshot identity/result;
- loads real payload or a safe typed failure state;
- auto-dismiss does not delete artifact;
- focus/hover behavior does not unexpectedly dismiss while interacting;
- Open works;
- Delete requires correct confirmation policy and updates view;
- Send to Jarvis uses the canonical attachment path and does not duplicate artifact bytes unnecessarily;
- Annotate is never rendered as active unless implementation exists;
- preview failure does not change capture state.

### Notification/status center

- same counts/categories as source model before/after relocation;
- click opens correct popup/list;
- unread/seen mutations remain correct;
- alert/completed/question categories use icon + text/aria, not color only;
- overflow counts and zero counts have defined behavior;
- bottom placement does not collide with interaction mode, rail, capture indicator or viewport safe area.

### Hidden-object toggle

- reflects current canonical visibility state;
- toggles same scene behavior as before;
- one toggle operation -> one canonical mutation;
- keyboard and screen-reader label describes resulting action/state;
- no permanent count capsule remains.

### Workspace rail

- current presentation rows preserved in content/action semantics;
- existing working/done/problem mapping stays correct;
- new changed/unreviewed state is shown only if canonical data exists;
- actual preview used when available; typed fallback when unavailable;
- no fake/stale image remains after item source changes beyond cache contract;
- click opens the correct source/surface;
- context actions remain available and honor playing/archived constraints;
- rail stays usable with Studio/Variantes open;
- right-side placement does not cover key scene interaction area more than specified;
- context switch refreshes rail to the new working set without leaking prior context items.

### Top chrome / global tools

Create a matrix of every pre-refactor permanent tool and its new route. Test that no required tool is orphaned.

## Visual regression / runtime validation matrix

At minimum capture screenshots or structured observations for:

1. default Board, wheel closed;
2. wheel open with Selection focused;
3. Selection submenu Mouse/Bare Hands;
4. Audio active;
5. Video active;
6. Screenshot preview visible;
7. bottom alert popover open;
8. right rail with mixed item types and statuses;
9. Studio/Variantes + rail;
10. interaction mode chooser open;
11. Board chooser open;
12. narrow desktop (< 900px);
13. short viewport (< 560px height);
14. reduced motion;
15. high zoom / 200% browser zoom where supported.

Compare to `assets/target-ui-reference.png` for composition, not pixel identity.

## Performance expectations

- Wheel open should feel immediate; no network request should be required merely to reveal it.
- Revealing the wheel must not trigger additional global polling loops.
- Rich previews must be lazy-loaded/size-bounded; the rail cannot decode every full-size video or presentation at once.
- Thumbnail failures must not create tight retries.
- Pointer/hand movement handling must avoid layout thrash; geometry should be precomputed or cheap.

## Accessibility checks

- full keyboard use;
- visible focus;
- screen-reader labels for all icon-only controls;
- status updates use appropriate live region without announcing timer every second if disruptive;
- color is never the sole status cue;
- target sizes remain usable, especially wheel wedges and bottom icons;
- tooltips are supplemental, never the only label.

## Human acceptance checks

Human checks live in each `human-validation.json` and are only run after automated validation is maximized. The final human pass should answer:

- Does the Board clearly dominate visually?
- Is the left anchor discoverable without looking like a permanent toolbar?
- Is Mouse/Bare Hands switching predictable rather than surprising?
- Can a user stop recording instantly without hunting?
- Can one glance at the right rail identify PowerPoint/Slides/video/image work?
- Do status counters feel informative rather than noisy?
- Does the UI match the approved dark orbital direction?
