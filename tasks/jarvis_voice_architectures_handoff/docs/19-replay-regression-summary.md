# Task19 replay regression summary

Accepted 2026-09-13.

| Scenario | Production seam | Corrected outcome |
| --- | --- | --- |
| `thinking_pause_wait` | Full `VoiceStack` | An uncertain thinking pause settles as WAIT with no filler, work dispatch or assistant-history mutation. |
| `stale_ack_35_9s` | `SpeechScheduler` + session metrics | The old acknowledgement is superseded at 28 seconds and cannot play when the device releases at 35.9 seconds; only the new result is spoken. |
| `backend_nonblocking_85_7s` | Full `VoiceStack` | Later turns remain admissible while the old backend work is pending; its late result becomes deferred stale-source state and is not auto-spoken. |
| `spoken_divergence` | `VoiceConversationState` + session metrics | Intended, generated and actually heard text remain distinct; completed mismatched playback increments divergence once. |
| `bus_cluster_7` | Realtime bridge ownership policy + session metrics | Seven rejected near-end candidates cause no duck, stop, cancel or Core work and count as seven rejected/false barge-ins. |
| `confirmed_interrupt_missing_item` | Realtime bridge + canonical state | Local playback stops, no impossible provider truncate is sent, no text is marked heard, and speech becomes cancelled. |
| `provider_cancel_after_generation` | Realtime bridge + guarded audio | Local stop remains authoritative after provider cancellation rejection and late PCM is discarded. |
| `missing_terminal_stall` | `SpeechScheduler` + session metrics | The first output times out as unknown rather than completed; queue state recovers and the next output can speak and persist. |
| `manual_close_late_results` | `PersistentVoiceRuntime` + scheduler + canonical state + session metrics | Manual close emits one frozen report; late Core results remain canonical but cannot speak or alter the report. |

All scenarios use strict, bounded JSON fixtures and one coherent fake clock.
Fake adapters reject accidental network, microphone or speaker access. Metrics
are derived only from diagnostics emitted by production components; tests do
not inject successful counter values directly.

The fixtures reconstruct the available September 11 transcript evidence.
They do not include raw audio or a recorded provider wire stream, so acoustic
behavior and provider-side cancellation/billing still require an explicitly
authorized live run.
