# Issue — conversation timeline long-poll saturates browser connections (main feature, amplified by scene)

Measured during integration (6 visible 1280×720 windows, one profile): each open conversation timeline holds one long-poll per tab. With the scene on (1 shared long-poll per profile), 5 open timelines stall `/api/status` for 5–14 s; 6 → 9–19 s and live events take ~14 s. Main alone saturates at 6 open timelines.

Suggested fix (change to main's feature, not done here): share the timeline long-poll across tabs like the scene's Web Lock leader + BroadcastChannel, or release it in hidden tabs.

Also noted on main (untouched): if Core startup fails after the conversation-event backfill queued an event, the emitter is never stopped; main's routes use `request.json()` rather than the strict bounded helper.

Update 2026-09-18: fixed on branch `fix/main-baseline-and-timeline` (HEAD `24d32d6`). One conversation-events long-poll per browser profile (Web Locks leader + BroadcastChannel, per-conversation lock), followers do bounded short reads only. Measured on the route: 10 windows → 1 long-poll (was 10); browser-side at 6+ windows `/api/status` 4 ms (was up to 24 s) and a live event reaches every window in ~20 ms (was 26 s). A blocker found by QA in the first attempt (switching conversation was a no-op in shared mode) is fixed and covered by 5 new tests.

Update 2026-09-18 (final integration, both features merged into `task/jarvis-constellation-scene-runtime`): measured for the first time with the two leaderships alive in the same profile — scene on by default plus a conversation timeline open in every window, own headless Chrome, counted on the routes themselves.

| windows | timeline long-polls | scene long-polls | total held | `/api/status` p50 / max | live event → every window |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | 1 | 2 | 3 / 3 ms | 15 ms |
| 6 | 1 | 1 | 2 | 3 / 4 ms | 50 ms |
| 10 | 1 | 1 | 2 | 3 / 4 ms | 19 ms (2 558 ms in one run, one window still settling) |

Two held connections whatever the number of windows, out of the browser's ~6 per host. The lock names (`jarvis.scene.leader` and `jarvis.timeline.<conversation_id>`) and the channel names (`jarvis.scene` and `jarvis.timeline`) are in disjoint namespaces, and a page that holds both leaderships behaves (roles observed `leader`/`follower` independently per feature, 0 page exceptions, 0 console errors). **No saturation.** Issue closed.
