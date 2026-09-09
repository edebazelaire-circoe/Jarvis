# 07 - Open Questions and Deferred Choices

These are not blockers for starting the ordered tasks. The implementation agent should resolve them using the simplest option consistent with the locked architecture and record any choice in `docs/01-decision-log.md` inside the working branch/task report.

## 1. Exact class names

`BrainOrchestrator`, `BrainWorkingState`, `SpeechRequest`, and `SpeechScheduler` are recommended names, not contractual API names. Semantics matter more than naming.

## 2. Brain state persistence format

The existing SQLite repository does not yet expose a dedicated brain-state entity. The simplest initial option may be to derive enough state from conversation turns + jobs and persist only a compact conversation-level public brain snapshot. Do not add a complex new schema unless restart behavior requires it.

## 3. Claude streaming transport

The current Control Center Claude API is final-response oriented. A streaming endpoint may be useful later. Do not block Core async ownership on implementing perfect model token streaming. Coarse accepted/work/final events are sufficient to land the architecture first.

## 4. Surface autonomous acknowledgement

There are two safe implementation options:

- allow Realtime prompt rules to generate a tiny acknowledgement automatically;
- have Core/surface code explicitly request a canned/templated acknowledgement.

Prefer the first only if tests show it remains inside the strict reflex boundary. Otherwise fall back to deterministic acknowledgements.

## 5. Microphone echo behavior

Continuous microphone input while speakers are active may cause acoustic feedback/VAD retriggers. This depends on hardware/driver layout. Keep a fallback mode and measure on the target workstation.

## 6. Event backpressure

`CoreEventBus` currently removes subscribers whose bounded queue fills. The initial SpeechScheduler should reconnect safely. If brain progress increases event volume, a later task may need per-event backpressure/coalescing. Do not silently make the bus unbounded.

## 7. Reconnect and replay

The current `/v1/events` bus is live-only. Durable job state already exists, but speech events are not replayed. Initial behavior should expire stale speech and rely on Core state/notifications after reconnect. A durable event log is a later enhancement unless tests prove it is required now.

## 8. Multiple sub-agents

Deferred. Use stable `work_id`, `correlation_id`, and optional parent/root metadata so later fan-out can be added without changing Voice contracts.

---

## 9. Provider metadata round-trip (opened by Task 04, 2026-09-09)

`speak()` correlates a `SpeechRequest` with the provider response by putting an
opaque `output_id` into `response.metadata` and reading it back from
`response.created`. The `response.cancel`, `conversation.item.truncate`, and input
transcription delta event shapes were confirmed against the official documentation.
`response.created`'s exact field set could not be read from the API reference (403 /
truncated pages); it is used on the strength of the names already present in the
adapter plus secondary sources.

**Consequence if wrong:** `speak()` still works and audio is still produced, but the
`speech_id` to `response_id` binding breaks silently - normalized events would carry
`speech_id: null` and `cancel_output()` would fall back to the active output.

**Widened after Task 12 (2026-09-09):** this is the system's named single point of
failure, and the consequence above was stated too narrowly. `_bind_response()`
(`jarvis/adapters/openai_realtime.py:235`) correlates by that metadata and by nothing
else, so a `speech_id: null` also corrupts persistence, not just cancellation: the
conversation bridge takes its reflex branch (`jarvis/runtime/realtime_audio.py:1367-1395`)
and writes the sentence with `provenance=surface.reflex`, while the speech scheduler
(`jarvis/runtime/speech_scheduler.py:715`) writes the same sentence with
`provenance=brain.speech`. That is the double persistence under a false provenance
which spec section 15 exists to prevent. No fallback correlation has been invented:
without the real provider nobody can say which one is right, and a guessed one would
hide the failure instead of exposing it.

**How this must be closed:** not by another unit test - the default suite is offline
by design. Add this assertion to the opt-in live provider test
(`tests/integration/test_live_openai.py`) in Task 11, and list it in the Task 12
workstation acceptance gate. Do not mark the architecture accepted until one real
session has shown `response.created` carrying the metadata back.

**Where it is tracked:** it is the first step of the `continuous_brain` workstation
checklist in `docs/ACCEPTANCE_STATUS.md` (in `runtime/trace.jsonl`, a
`voice.output_started` event for a brain speech must carry a non-null `speech_id`),
and a named limitation in `docs/handoff-realtime-brain/FINAL-REPORT.md`.

## 10. Brain speech bypasses the persona instructions (opened by Task 04)

`speak()` sends a verbatim reading instruction at response level, which replaces the
session instructions for that one response. Voice timbre still comes from
`audio.output.voice`, but the textual persona does not apply to brain speech.

This is intended: Decision 13 requires the surface to render brain output faithfully
rather than reinterpret it. Task 06 must not "fix" this by reinjecting the persona
into the brain speech path. If diction guidance is genuinely needed, it may be added
to the verbatim instruction only if it cannot alter the words spoken.
