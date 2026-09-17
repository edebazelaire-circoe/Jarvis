# Issue — conversation timeline long-poll saturates browser connections (main feature, amplified by scene)

Measured during integration (6 visible 1280×720 windows, one profile): each open conversation timeline holds one long-poll per tab. With the scene on (1 shared long-poll per profile), 5 open timelines stall `/api/status` for 5–14 s; 6 → 9–19 s and live events take ~14 s. Main alone saturates at 6 open timelines.

Suggested fix (change to main's feature, not done here): share the timeline long-poll across tabs like the scene's Web Lock leader + BroadcastChannel, or release it in hidden tabs.

Also noted on main (untouched): if Core startup fails after the conversation-event backfill queued an event, the emitter is never stopped; main's routes use `request.json()` rather than the strict bounded helper.
