# Task07 canonical manifest integration evidence

Canonical subdelivery for parent/lead integration review; this document does not mark Task07 complete or claim a hardware test.

## Contract and ownership

- New neutral types: `jarvis.domain.voice_playback` (`VoiceAudioPart`, `VoiceAudioPartExtent`, `VoicePlaybackManifest`, `VoiceDevicePlaybackProof`, `VoiceDevicePlaybackStatus`). Exact item/content/output indices, session/local output/provider response, bytes and device operation/epochs are separate from generated/intended text.
- Existing production facade now calls the bounded manifest helper for every canonical event. Lead's playout worker calls `playback_manifest(payload)`, then its real `audio.complete_output(manifest)`, then `observe_device_completion(manifest, proof)`. No second provider reader, PCM ingress or assistant-history writer is introduced.
- Only explicit completed Realtime response inventory closes all parts. Known audio/output_audio content is supported; text/output_text is excluded, unknown content or incomplete message invalidates eligibility. Final manifest transcripts cross-check callback finals. No GPT-Live final is inferred from silence.
- Actual device worker owns epoch, stream identity, checked native stop, invalidation and cleanup truth. The helper accepts only full matching received/written/confirmed part byte extents. The provider does not publish an expected PCM byte total; therefore this checks internal receipt-to-write integrity and cannot certify hypothetical upstream missing bytes.
- Effective retention: 128 output records, 16 parts per output, 8192 characters of final transcript per output. Neutral type/codec bounds permit 128 parts, but that is not an effective runtime capacity claim. Eviction/restart loses pending eligibility conservatively.
- Missing/nonclosed/zero-audio parts, dropped writes, status failures, ambiguous indices, extra closure, late audio, changed transcript and invalidated output cannot produce COMPLETE text. A coherent late first final can join the old exact proof after a newer response starts; explicit close/interruption prevents later promotion.
- Part-relative truncate now preserves `PlaybackCursor.content_index` through `AssistantPlaybackEvidence.part` to provider control. It is bounded by the corresponding received part, not the last generated part. No words are inferred from partial duration.

## Compatibility and state

Version1 canonical events accept only newly optional missing part/inventory fields as unknown. Snapshot `VoiceGeneratedText.part` preserves item/content/output indices; old version1 generated records without that field load with `None`. Unknown fields, boolean/negative indices and malformed nested parts are rejected. Existing historical confirmation remains intact; snapshots do not persist or recreate live device authority.

Task06 exact reserved-response cancellation, sole reader, lifecycle terminal ownership and unstarted preamble guard remain. No files in the lead's device/runtime scope are modified by this subdelivery.

## Tests

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_voice_playback_manifest.py tests/unit/test_realtime_output_control.py tests/unit/test_realtime_frontend_adapter.py tests/unit/test_realtime_frontend_pipeline.py tests/unit/test_voice_event_codec.py tests/unit/test_voice_conversation_state.py tests/unit/test_voice_ledger_protocol.py tests/unit/test_reflex_frontend_cleanup.py tests/unit/test_v2_architecture.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

2026-09-12: **178 passed in 10.37 s**. New manifest suite: 28 cases through actual low-level normalization, canonical frontend/facade, dispatcher, Core ledger and SQLite, with controlled wire and explicitly injected proof values. This validates the join and projection, not a physical/native drain.

Positive coverage: three audio parts including two in one item; generated finals in exact indexed records; valid proof before last transcript; last transcript arrives after a newer output; one full heard history range; duplicate proof; version1 snapshot roundtrip/migration; mixed known text/audio content; strict indexed event codec.

Negative coverage: missing expected part, unclosed part, zero audio, wrong item/output index, cancelled/incomplete response, incomplete message, unknown content, missing inventory, missing written bytes, wrong session/output, interruption, unknown drain status, late extra part closure, late audio, delta after final and final-inventory transcript contradiction. Every invalid case prevents a new heard projection. Truncate test sends part0 (20 ms) and part1 (100 ms), then requests 80 ms while part0 is playing: actual provider command targets content_index0 and audio_end_ms20.

## Observability / limits

The manifest helper is a pure in-memory evidence join and adds no raw-text journal entries. The existing dispatcher/Core ledger emit their normal canonical state/projection diagnostics; high-frequency PCM is replaced by cumulative duration before authenticated Core ingress. Failure and native drain diagnostics remain with the lead's existing RuntimeJournal integration. No new logger or temporary probes.

Full natural device playback, blocked-driver ownership, stop/timeout races and real production factory validation require the lead/parent integration gate. Synthetic proof objects here must never be presented as measurements of speaker output, listener perception, partial-word timing or hardware latency.

Response-start dedup retains at most 4096 IDs per provider session; duplicate starts cannot reopen old outputs after detailed mapping eviction. Saturation raises an explicit transport-boundary failure and uses existing frontend cleanup. Detailed low-level output mapping remains 32 outputs; therefore very late transcripts beyond that mapping retention remain unknown even if a helper record still exists. Tests cover 140 starts, replay of evicted response 0 and retention saturation.
