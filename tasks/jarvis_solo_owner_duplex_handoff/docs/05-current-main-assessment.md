# 05 — Current `main` Assessment

Baseline reviewed: `8fc7a117791f39eba70362cb2acd56ecbc8e44fa`.

## Keep

| Current behavior/module | Decision |
|---|---|
| WebRTC AEC3 via LiveKit | Keep |
| Noise suppression / high-pass | Keep; benchmark interactions |
| `NearEndDetector` | Keep as acoustic prefilter |
| Echo guard | Keep; adapt gate authority in Solo Owner |
| Pre-roll concept | Keep; separate/extend owner-verification buffer |
| Decoupled provider reader / playout / main task | Keep absolutely |
| Local `stop_output()` before provider cancel | Keep absolutely |
| Cancel + truncate with degraded handling | Keep |
| Transcript filters | Keep as defense in depth |
| Engagement window / uncertain addressing | Keep for verified owner speech |
| `server_vad` / `semantic_vad` settings | Keep |
| Contextual delayed acknowledgement | Keep |
| Core-owned async brain | Keep absolutely |
| `AgentTaskTracker` | Keep as provider-specific observer |

## Change

| Current behavior | Target |
|---|---|
| generic `near_end` ducks volume to 30% | no audible action before owner confirmation in Solo Owner |
| provider `speech_started` confirms barge-in | local owner confirmation authorizes local stop; provider signal advisory |
| short pre-roll tuned for acoustic detector | add longer configurable owner-verification ring buffer |
| gate opens when far-end is absent | in Solo Owner, only verified owner audio may become conversational input |
| detailed task state lives primarily in runtime/UI | normalize into Core-owned work state |

## Add

- `SpeakerVerifier` typed port.
- owner profile/enrollment lifecycle.
- shadow/enforce modes.
- explicit `solo_owner` conversation mode separate from `continuous_brain`.
- owner-verification metrics and hardware benchmark.
- Core normalized work-state service/store/events.
- brain context containing bounded current work details.
- UI read path from Core work projection.
