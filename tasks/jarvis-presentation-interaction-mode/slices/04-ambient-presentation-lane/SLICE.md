# Slice 04 — Ambient Presentation context lane

## Goal

Feed live presentation speech into Presentation context while structurally preventing ambient speech from becoming an addressed command/turn.

## Context

Completed capture/session work already distinguishes the memory-only PRESENTATION ambient lane from explicit durable recording. This Slice integrates that lane with Presentation semantics.

## Canonical Concepts

Ambient lane, transcript segment, explicit address, authority classification, conversation event, capture privacy boundary.

## Scope

### In Scope

- Consume existing ambient transcript segments while PRESENTATION is active.
- Carry stable IDs/timestamps/freshness and an explicit non-authoritative classification.
- Keep ambient transcript out of canonical addressed conversation turns.
- Stop/ignore Presentation-only ambient interpretation promptly when mode exits.
- Provide deterministic replay/fake hooks for later tests.

### Out of Scope

- Persisting raw ambient PCM as a recording.
- Treating arbitrary room speech as a command.
- Long-term semantic memory.

## Dependencies

- `02-interaction-mode-contract`
- `01-contract-reconciliation`

## Implementation Steps

1. Reuse current ambient capture/transcription path.
2. Add/verify structural authority metadata.
3. Define bounded fresh-segment delivery to Presentation context.
4. Ensure explicit-address routing remains separate and higher priority.
5. Add privacy and authority regression tests.

## Files Likely Touched

Ambient lane, transcription event schema/adapters, Presentation context glue, tests, docs.

## Architecture Constraints

No implicit durable recording; no LLM-only prompt convention as the authority boundary.

## Automated Validation

Replay tests proving ambient monologue cannot dispatch addressed actions and mode exit stops Presentation consumption.

## Acceptance Criteria

Presentation receives fresh ambient context with provenance, while canonical conversation/action authority remains unchanged.

## Documentation Updates

Document ambient authority and privacy semantics.

## Handoff Notes

Coding/runtime Slice: load `/caveman` and `/coding-guideline`; add `agent-trace-analysis` because routing/authority behavior changes.


## Slice 00 contract (binding)

Scope in:
- **P2 authority rule, structural.**
  - Pure helpers in `domain/presentation_addressed_turn.py`: `is_vocative_address(text)` (same normalization as `realtime_audio.py:266-269`, prefix only) and `TurnAuthority`.
  - `RealtimeConversationBridge` takes an optional `presentation_turns` reader, wired from `voice_v2.py` `presentation_turns`. `_handle_admitted_transcript` (`realtime_audio.py:4536`) applies the rule **before** the UNCERTAIN route (:4580), direct admission (:4656) and submit (:4691).
  - When no live session exists, the code path is unchanged.
- **P3 open before submit.**
  - Compute the correlation via `_brain_correlation_id`.
  - Call `turns.open(...)` before `_submit_brain_turn`.
  - `_submit_brain_turn` accepts the precomputed correlation.
  - `SpeechScheduler.note_addressed_turn(text, correlation_id=, plan=)` uses the given plan and never reopens (`speech_scheduler.py:719-760`).
  - Window-refusal codes mean "not authorized"; other refusals mean authorized without a plan.
- **P10.** On the ambient branch in PRESENTATION, `voice.transcript` (:4556) carries `chars` and `addressing` only. The transcript text goes nowhere: no `voice.transcript_dropped` text, no admission.
- Verify the manual key during an ACTIVE session reaches `turns.arm` (`wakeword_keyboard.py:58-62` → `PresentationWakeRouter._label` `presentation_runtime.py:714-734`). If it does not, make it.
- Verify, for direct-conversation architectures, that a non-admitted item produces no audible output. If it does, stop and report to the PM.

Scope out:
- SIMPLE routing;
- the classifier heuristics themselves;
- audio-level gating of the realtime stream;
- the brain context (05);
- Issue 002 on the SIMPLE path (11).

Files: `jarvis/runtime/realtime_audio.py`, `jarvis/runtime/voice_v2.py`, `jarvis/runtime/speech_scheduler.py`, `jarvis/core/presentation_addressed_turn.py` (only if a code is missing), `jarvis/domain/presentation_addressed_turn.py`, `docs/presentation-addressed-turn.md`, `docs/presentation-ambient-lane.md` (authority section), new `tests/unit/test_presentation_turn_authority.py`.

Acceptance (`test_presentation_turn_authority.py`; real bridge, fake core/session/turns as in `tests/unit/test_conversation_event_voice_bridge.py`):
- `test_room_speech_without_window_never_reaches_the_brain`: engaged, `"on passe au slide suivant ?"` → `submit_brain_turn` not called, `on_addressed` not called.
- `test_uncertain_room_speech_is_not_routed_in_presentation`.
- `test_armed_window_admits_exactly_one_turn`: the second transcript without a re-arm is ambient.
- `test_vocative_prefix_is_explicit_address_without_window` and `test_third_person_mention_is_not_address` (`"comme Jarvis l'a montré hier"`).
- `test_jarvis_mute_still_mutes_in_presentation`.
- `test_addressed_turn_opened_before_submission_and_not_reopened`: call order recorded; scheduler `open` count = 1.
- `test_manual_key_during_active_session_arms_a_window`.
- `test_direct_architectures_apply_the_same_guard`.
- `test_guard_holds_with_presentation_brief_blanked`: monkeypatch `BRIEF_PRESENTATION_MODE=""` → same result (structural, HD3).
- `test_ambient_segment_text_never_reaches_trace`: planted phrase, real `RuntimeJournal` on tmp, phrase absent from `trace.jsonl`.
- `test_simple_routing_unchanged`: parametrized over the classifier cases with `presentation_turns=None` and with mode SIMPLE → identical submit/addressing calls.
- `test_mode_exit_restores_simple_routing`.
- Existing `test_presentation_*`, `test_conversation_event_voice_bridge.py`, `test_owner_barge_in.py` and `test_speech_presentation*` green.

QA tier: critical. Passes:
- qa-verification + code-review + runtime-validation (fake-driven replay through the composed stack);
- agent-trace-analysis on a real trace: an ambient monologue yields no `voice.brain_turn_submitted`; an addressed turn shows `presentation.addressed.opened` before submission;
- mutation: ≤10 mutants, foreground, on the guard predicate, vocative check, window refusal mapping, one-turn consumption and P3 ordering. The harness refuses a red baseline and carries one cosmetic control that must survive.

Not yours: transport of context (05); timeline (10); SIMPLE trace text (11).

Depends on: 01, 02.

Documentation: ambient vs addressed authority Level 3.
