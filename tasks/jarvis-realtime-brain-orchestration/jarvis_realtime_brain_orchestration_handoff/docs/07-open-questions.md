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
