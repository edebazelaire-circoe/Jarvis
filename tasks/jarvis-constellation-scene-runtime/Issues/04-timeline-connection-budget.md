# Issue — conversation timeline long-poll saturates browser connections (main feature, amplified by scene)

Measured during integration (6 visible 1280×720 windows, one profile): each open conversation timeline holds one long-poll per tab. With the scene on (1 shared long-poll per profile), 5 open timelines stall `/api/status` for 5–14 s; 6 → 9–19 s and live events take ~14 s. Main alone saturates at 6 open timelines.

Suggested fix (change to main's feature, not done here): share the timeline long-poll across tabs like the scene's Web Lock leader + BroadcastChannel, or release it in hidden tabs.

Also noted on main (untouched): if Core startup fails after the conversation-event backfill queued an event, the emitter is never stopped; main's routes use `request.json()` rather than the strict bounded helper.

Update 2026-09-18: fixed on branch `fix/main-baseline-and-timeline` (HEAD `24d32d6`). One conversation-events long-poll per browser profile (Web Locks leader + BroadcastChannel, per-conversation lock), followers do bounded short reads only. Measured on the route: 10 windows → 1 long-poll (was 10); browser-side at 6+ windows `/api/status` 4 ms (was up to 24 s) and a live event reaches every window in ~20 ms (was 26 s). A blocker found by QA in the first attempt (switching conversation was a no-op in shared mode) is fixed and covered by 5 new tests.
