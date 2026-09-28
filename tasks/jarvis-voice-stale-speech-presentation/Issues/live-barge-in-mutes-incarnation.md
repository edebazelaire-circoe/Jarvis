# Live barge-in mutes the surface until the incarnation ends

- Found: Slice 00 audit, 2026-09-28, at `202333d`.
- `RealtimeAudioBridge._barge_in` calls `suppress_playback_until_session_end()` on Live (`jarvis/runtime/realtime_audio.py:1762-1764`); `LiveFrontendSession` then drops every later output of that session (`jarvis/runtime/live_frontend_session.py:365-373`).
- Effect: after one Live barge-in, whatever the scheduler dispatches (including a speech the brain re-emits under Slice 04) is inaudible until a reconnection. Probable contributor to "Jarvis stops answering" reports, and it interacts with the queue freeze of Slice 05.
- Owner: Slice 05 freshness-check decides whether it is handled there (reconnect or re-arm playback on the next addressed turn) or stays an Issue for a follow-up handoff.
