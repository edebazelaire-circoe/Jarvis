# Task06 implementation evidence

Implementation submitted for parent review; no TODO/status or commit changes by the implementation agent.

## Observable contract

- Feature: deliberate reflex silence/preamble. Channel: existing RuntimeJournal (trace.jsonl, error policy unchanged). Pure domain.reflex_policy and worker OutputAdmission do not log.
- Identity: existing admitted Brain correlation and conversation IDs; reserved local output ID maps to provider response ID through existing metadata. No invented task or provider input ID.
- Normal evidence: voice.reflex.decided info includes action/reason/phase/elapsed_ms. WAIT creates no speech output. voice.reflex.started states generation was requested. voice.reflex.skipped plus invalidation WAIT explain supersession. There is no text-content logging in these new observations.
- Failure evidence: existing voice.speech.speak_failed warning with reflex_speak_failed or reflex_cancel_failed and sanitized exception type; reservation mismatch uses reflex_output_identity_mismatch. Canonical cancellation-control failure emits typed transport/timeout failure and terminal UNKNOWN_REAP_REQUIRED after owned cleanup. CancelledError propagates.
- Recovery: useful Core answers retain existing scheduling. Exact stale response cancellation never targets its successor. Gap in Core events discards cached work evidence; session-retention saturation chooses silence. A new runtime session creates a new scheduler. No automatic provider/session reopen.
- Temporary probes: none. Test wire/device doubles are confined to tests. The existing Task05 temporary façade remains governed by its documented migration removal criterion.

## Validation

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_reflex_gate.py tests/unit/test_reflex_frontend_cleanup.py tests/integration/test_reflex_preamble_race.py tests/unit/test_voice_duplex.py tests/unit/test_realtime_audio_lifecycle.py tests/unit/test_v2_speech_scheduler.py tests/unit/test_realtime_frontend_adapter.py tests/unit/test_realtime_frontend_pipeline.py tests/unit/test_surface_reflex_policy.py tests/integration/test_voice_production_composition.py tests/unit/test_voice_frontend_contract.py tests/unit/test_v2_architecture.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

2026-09-12: **285 passed in 13.53 s**. Warnings are errors. Includes existing admission/owner, continuous/legacy, device epochs, scheduler, canonical ledger/history, startup/stop/transport and real app composition regressions. Parent separately reports **567 passed in 22.07 s**, including broader Core, owner/replay/barge-in, app/environment and migration coverage.

New policy coverage: standalone OK; typographic decline; thinking/continuation; corrections; substantive request beginning OK; useful Core answer preserved through WAIT; work before/after request; terminal/reordered work; stream/revision gaps; duplicate live and expired requests; bounded state/payload; retention saturation; native-write deadline without an asyncio tick.

New production race coverage uses the actual low-level normalizer, canonical frontend, façade, Core ledger/SQLite, bridge and SoundDevice writer, controlling external transport and native stream only:

- Useful result from the same or another correlation during blocked response.create invalidates the reserved preamble before any PCM write; repeated invalidation sends one cancellation for that exact response.
- Invalidation while the worker waits for the existing device lock produces no write and no first_audio/on_speaking observation.
- Result after WRITE_STARTED cannot rewrite that attempt as proven unplayed.
- Expiry while response creation is held drops late PCM without needing another user/Core event.
- Blocked cancel send, duplicate response.created and a newer useful response do not block user input/terminal processing or target the successor. Close joins the cancellation task.
- Follow-up Task05 lifecycle repair: EOF arriving before transport close acknowledgement cannot end an active event consumer before the final STOPPED/UNKNOWN event. Both normal Stop and deferred cancellation failure are covered.

Generated transcript remains visible while played_ms=0 and confirmed_text=None; no assistant heard history is archived for dropped preambles. Tests do not inject fictitious hardware completion to claim real heard words.

## Fixture and journal evidence

test_synthetic_replay_reduces_filler_and_retains_both_long_work_preambles adapts text shapes from [replay-fixture-extraction-notes.md](replay-fixture-extraction-notes.md), with explicit synthetic correlation IDs, work events and timing. Nine cases include required controls, ambient admission, fast answer, missing work evidence and two genuine long-wait positives.

Counterfactual previous trigger (admitted, at least 4 words, no useful answer yet) permits 6 preambles; current real scheduler creates 2: **67% reduction**, with both long-wait positives retained. This is a bounded deterministic policy comparison, not historical playback reconstruction, full Task19 replay or evidence of perceived acoustic quality. Duplicate source log lines do not prove duplicate playback.

The same test writes real RuntimeJournal events and inspects them through the repository-supported read_jsonl_tail helper. It verifies info-level decisions, nonnegative latency and correlation, absence of raw fixture text, and no errors file. The generic skill's observability.cli module is absent from this repository; no parallel logging system was introduced.

## Remaining limitations

The textual gate is a small French conversational heuristic, not a semantic planner. BACKCHANNEL and DELEGATE are reserved/advisory values without production execution. Existing owner gate controls ambient input before reflex requests; rejected ambient input retains its existing admission trace rather than fabricating a reflex correlation.

A native write already in progress cannot be proven unplayed. Task06 does not change PortAudio cancellation or device drain. Positive written duration still does not establish a complete heard transcript; Task07 must close that Task05 evidence gap before architecture switch 17 / benchmark 20. The broad fixed acknowledgement allowance in historical continuous-brain session instructions remains compatibility prompt text, while the actual preamble generation prompt and gate are changed.
