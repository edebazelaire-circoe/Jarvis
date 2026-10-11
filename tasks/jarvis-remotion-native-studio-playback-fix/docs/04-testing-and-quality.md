# QA, runtime evidence and Human acceptance


## Mandatory review matrix


For **every** implemented Slice: `qa-verification`. If code changes: `code-review`. If visible UI or runtime changes: `runtime-validation`. If agent prompts, routing, tools or runtime change: `agent-trace-analysis` with real traces. QA reports evidence; only PM approves/reworks/escalates. Current-Slice regressions are blocking, never transferred to `Issues/`. After strongest possible machine verification, ask Human only for physical/qualitative checks.


## Must-have automated cases


- Full 9-scene source with varied animation lengths; 3s, 8s and 30s scenes; mixed fps when supported; scene markers and transitions.
- Start at scene 1 frame 0, play to end, stop/hold correctly; replay starts at frame 0.
- Scene 5 -> 6 via click, next and timeline, always enters correct local frame and no stale carry.
- Scrub Player bar -> scene UI, thumbnail and global timeline update; scrub other UI -> Player updates. Repeated bidirectional seek at high frequency remains deterministic.
- Video doesn't cut 30s scene at 8s; manual score/cues can't silently override video duration.
- Transition adjacency: no unjustified blank/white frame, half-played next scene, duplicate music or flicker.
- Focus, hot reload, frame-level pause, Chrome fullscreen user gesture, resize, 1080p, audio mute/unmute and recoverable errors.
- Browser Cold/Warm Studio open, Studio source change and persistence, Variants preview same version; existing variants stay intact.
- No access to old floating viewer via graphical actions, voice/MCP or restored stale preferences.
- Source diff, sandbox and license checks for agent-native TSX/projects; snapshots/render/export provenance preserved.
- Agent benchmark: direct Claude+Remotion and Jarvis with same user brief/data, compare generated source, tool traces, visual frames and human blinded judgement.


## Evidence package


Store actual runtime, git SHA, OS/Chrome/Node/Remotion versions, isolated ports, source digest, storyboard and timing manifest, screenshot/video captures, per-frame time markers, baseline diffs, artifact integrity and QA reports. Record test command, pass/fail and skipped coverage. A code-reading assumption is not a passed runtime test.


## Human validation after machine gates


1. Watch complete deck with 9 scenes and real transitions, including a 30s scene; check visual stutter, initial frames and final state.
2. Use actual mouse/keyboard/play controls and compare scrub bars/scene selection.
3. Validate Variants interface control density, Studio/Variants navigation and disappearance of old viewer.
4. On real screen/projector + speakers, check fullscreen, audio and optional voice presentation.
5. Compare blinded direct-Remotion and Jarvis-made decks for quality, not just generated-file validity.
6. Validate any trust and licensing decisions requiring the owner.


## Performance/acceptance framing


No invented numeric SLA before instrumentation. Slice 03 measures baseline; PM sets target based on a user-visible uninterrupted full playback and observed native Remotion reference. Zero unexpected visible blank/flash frames at scene switches is the acceptance ideal. Every intentional transition must be distinguishable from defects.