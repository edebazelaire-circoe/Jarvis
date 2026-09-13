from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from jarvis.domain.voice_architecture import SimpleVoiceConfig, VoiceModelRef
from jarvis.domain.voice_events import (
    AssistantAudioChunk, AssistantGenerationFinished, AssistantGenerationStarted,
    AssistantPlaybackEvidence, AssistantSpeechActivity, AssistantTranscriptCompleted,
    AssistantTranscriptDelta, FrontendLifecycleChanged, UserCommitSource,
    UserInterruption, UserSpeechActivity, UserTranscriptCommitted, UserTranscriptDelta,
    UserTurnOpened, VoiceActivitySource, VoiceDelegationRequested, VoiceEvent,
    VoiceFrontendFailed, VoiceGenerationStatus, VoiceInterruptionStage,
    VoicePlaybackStatus, VoiceSpeechPhase, VoiceUsageSource, VoiceUsageUpdated,
)
from jarvis.domain.voice_frontend import (
    FrontendState, ProviderDelegationId, ProviderInputId, ProviderOutputId,
    ProviderSessionId, VoiceAudioChunk, VoiceContext, VoiceContextMessage,
    VoiceContextRole, VoiceCorrelation, VoiceErrorCode, VoiceFrontendConfig,
    VoiceFrontendError, VoiceObservation, VoiceOperation, VoiceOperationId,
    VoiceOperationKind as Kind, VoiceOperationResult, VoiceOperationStatus as Status,
    VoicePcmFormat, VoiceSessionId, VoiceSessionInterval, VoiceSpeechId,
    VoiceStopReason, VoiceTaskId, VoiceTextUpdate, VoiceTranscriptId, VoiceTurnId,
)
from jarvis.ports.voice_frontend import VoiceFrontend
from tests.fakes.voice_frontend import FakeVoiceFrontend


SESSION = VoiceCorrelation(VoiceSessionId("opaque-session"), provider_session_id=ProviderSessionId("opaque-remote"))
TURN = replace(SESSION, turn_id=VoiceTurnId("turn-one"), provider_input_id=ProviderInputId("input-one"))
OUTPUT = replace(TURN, task_id=VoiceTaskId("task-one"), speech_id=VoiceSpeechId("speech-one"), provider_output_id=ProviderOutputId("output-one"))
CONFIG = VoiceFrontendConfig(SimpleVoiceConfig(VoiceModelRef("test-provider", "test-model")))


def operation(name: str, correlation: VoiceCorrelation = SESSION) -> VoiceOperation:
    return VoiceOperation(VoiceOperationId(name), correlation)


async def started(**kwargs) -> FakeVoiceFrontend:
    frontend = FakeVoiceFrontend(**kwargs)
    result = await frontend.start(CONFIG, operation=operation("start"))
    assert result.status == Status.COMPLETED
    return frontend


async def drain(frontend: FakeVoiceFrontend) -> list[VoiceEvent]:
    return [event async for event in frontend.events()]


async def test_complete_synthetic_conversation_preserves_evidence_and_order_without_sdk():
    frontend = await started()
    assert isinstance(frontend, VoiceFrontend)
    reader = asyncio.create_task(drain(frontend))
    input_id = VoiceTranscriptId("input-transcript")
    output_id = VoiceTranscriptId("generated-transcript")
    input_events = [
        UserSpeechActivity(VoiceSpeechPhase.STARTED, VoiceActivitySource.LOCAL),
        UserTurnOpened(None, VoiceActivitySource.PROVIDER),
        UserTranscriptDelta(input_id, "Tell ", 0),
        UserTranscriptDelta(input_id, "me.", 1),
        UserSpeechActivity(VoiceSpeechPhase.STOPPED, VoiceActivitySource.PROVIDER),
        UserTranscriptCommitted(input_id, "Tell me.", 2, UserCommitSource.PROVIDER),
    ]
    for payload in input_events:
        frontend.inject(frontend.event(payload, correlation=TURN))
    delegation = replace(TURN, provider_delegation_id=ProviderDelegationId("arbitrary-delegation"))
    frontend.inject(frontend.event(VoiceDelegationRequested(2), correlation=delegation))
    update = VoiceTextUpdate("Backend intended answer", context_revision=2)
    result = await frontend.append_spoken_result(update, operation=operation("speak", OUTPUT))
    assert result.status == Status.ACCEPTED
    generated = "Provider paraphrased answer."
    output_events = [
        AssistantGenerationStarted(),
        AssistantTranscriptDelta(output_id, "Provider "),
        AssistantTranscriptCompleted(output_id, generated),
        AssistantPlaybackEvidence(VoicePlaybackStatus.UNPLAYED, 0),
        AssistantAudioChunk(VoiceAudioChunk(b"\0\0" * 240)),
        AssistantSpeechActivity(VoiceSpeechPhase.STARTED),
        AssistantGenerationFinished(VoiceGenerationStatus.COMPLETED),
        AssistantSpeechActivity(VoiceSpeechPhase.STOPPED),
        AssistantPlaybackEvidence(VoicePlaybackStatus.COMPLETE, 10, generated),
    ]
    for payload in output_events:
        frontend.inject(frontend.event(payload, correlation=OUTPUT))
    frontend.inject(frontend.event(VoiceUsageUpdated(VoiceUsageSource.PROVIDER_FINAL, 4.5)))
    await frontend.stop(VoiceStopReason.USER, operation=operation("stop"))
    observed = await asyncio.wait_for(reader, 1)
    assert [event.sequence for event in observed] == list(range(1, len(observed) + 1))
    assert [event.payload for event in observed[2:8]] == input_events
    assert observed[8].correlation.provider_delegation_id == "arbitrary-delegation"
    assert [event.payload for event in observed[9:18]] == output_events
    assert output_events[2].text != update.text
    assert output_events[3].confirmed_text is None
    assert all(event.correlation == OUTPUT for event in observed[9:18])
    assert observed[-1].payload == FrontendLifecycleChanged(FrontendState.STOPPED)


@pytest.mark.parametrize("kind,method", [
    (Kind.QUIET_CONTEXT, "append_quiet_context"),
    (Kind.SPOKEN_RESULT, "append_spoken_result"),
    (Kind.RUNTIME_INSTRUCTION, "feed_runtime_instruction"),
    (Kind.CANCEL_SPEECH, "cancel_speech"),
    (Kind.FINISH_INPUT, "finish_input"),
    (Kind.SEND_AUDIO, "send_audio"),
])
async def test_unsupported_controls_never_pretend_success_or_fabricate_output(kind, method):
    frontend = await started(supported=frozenset(Kind) - {kind})
    args = () if kind in {Kind.CANCEL_SPEECH, Kind.FINISH_INPUT} else (
        VoiceAudioChunk(b"\0\0") if kind == Kind.SEND_AUDIO else VoiceTextUpdate("private context"),
    )
    result = await getattr(frontend, method)(*args, operation=operation("unsupported"))
    assert result.status == Status.UNSUPPORTED
    assert result.error.code == VoiceErrorCode.UNSUPPORTED
    assert len(frontend.calls) == 1
    await frontend.stop(VoiceStopReason.USER, operation=operation("stop"))
    assert all(isinstance(event.payload, FrontendLifecycleChanged) for event in await drain(frontend))


async def test_acceptance_does_not_invent_ack_speech_or_transcript_and_pcm_matches_config():
    frontend = await started()
    assert (await frontend.send_audio(VoiceAudioChunk(b"\0\0"), operation=operation("audio"))).status == Status.ACCEPTED
    mismatch = await frontend.send_audio(VoiceAudioChunk(b"\0\0", VoicePcmFormat(16000)), operation=operation("wrong-rate"))
    assert mismatch.error.code == VoiceErrorCode.INVALID_INPUT
    for method in (frontend.append_quiet_context, frontend.append_spoken_result, frontend.feed_runtime_instruction):
        assert (await method(VoiceTextUpdate("bounded text"), operation=operation(method.__name__))).status == Status.ACCEPTED
    assert (await frontend.finish_input(operation=operation("finish"))).status == Status.ACCEPTED
    assert (await frontend.cancel_speech(operation=operation("cancel", OUTPUT), playback=AssistantPlaybackEvidence(VoicePlaybackStatus.PARTIAL, 2))).status == Status.ACCEPTED
    await frontend.stop(VoiceStopReason.USER, operation=operation("stop"))
    assert all(isinstance(event.payload, FrontendLifecycleChanged) for event in await drain(frontend))


@pytest.mark.parametrize("before_start", [False, True])
async def test_double_stop_is_safe_and_wakes_waiting_reader(before_start):
    frontend = FakeVoiceFrontend() if before_start else await started()
    reader = asyncio.create_task(drain(frontend))
    first = await frontend.stop(VoiceStopReason.SHUTDOWN, operation=operation("stop-one"))
    second = await frontend.stop(VoiceStopReason.USER, operation=operation("stop-two"))
    assert first.status == second.status == Status.COMPLETED
    assert second.operation.operation_id == "stop-two"
    assert sum(kind == Kind.STOP for kind, _, _ in frontend.calls) == 1
    observed = await asyncio.wait_for(reader, 1)
    assert sum(event.payload == FrontendLifecycleChanged(FrontendState.STOPPED) for event in observed) == 1
    assert await drain(frontend) == []
    assert (await frontend.start(CONFIG, operation=operation("restart"))).status == Status.REJECTED


async def test_uncertain_close_terminates_iterator_without_claiming_stopped():
    frontend = await started(close_confirmed=False)
    reader = asyncio.create_task(drain(frontend))
    result = await frontend.stop(VoiceStopReason.ERROR, operation=operation("stop"))
    assert result.status == Status.UNKNOWN
    assert result.error.code == VoiceErrorCode.CLOSE_UNCONFIRMED
    assert result.state == FrontendState.UNKNOWN_REAP_REQUIRED
    assert result.operation.correlation.provider_session_id == "opaque-remote"
    assert (await frontend.stop(VoiceStopReason.USER, operation=operation("again"))).status == Status.UNKNOWN
    assert not any(event.payload == FrontendLifecycleChanged(FrontendState.STOPPED) for event in await asyncio.wait_for(reader, 1))
    assert (await frontend.start(CONFIG, operation=operation("duplicate-start"))).status == Status.REJECTED


async def test_stop_during_start_unblocks_start_without_late_active_state():
    frontend = FakeVoiceFrontend(start_gate=asyncio.Event())
    task = asyncio.create_task(frontend.start(CONFIG, operation=operation("start")))
    await asyncio.wait_for(frontend.start_entered.wait(), 1)
    await frontend.stop(VoiceStopReason.USER, operation=operation("stop"))
    assert (await asyncio.wait_for(task, 1)).status == Status.REJECTED
    assert not any(event.payload == FrontendLifecycleChanged(FrontendState.ACTIVE) for event in await drain(frontend))


@pytest.mark.parametrize("max_events", [1, 256])
async def test_cancelled_start_preserves_cleanup_ownership_and_propagates_cancellation(max_events):
    frontend = FakeVoiceFrontend(start_gate=asyncio.Event(), close_confirmed=False, max_events=max_events)
    task = asyncio.create_task(frontend.start(CONFIG, operation=operation("start")))
    await asyncio.wait_for(frontend.start_entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert frontend.state == FrontendState.UNKNOWN_REAP_REQUIRED
    await frontend.stop(VoiceStopReason.CANCELLED, operation=operation("stop"))
    observed = await asyncio.wait_for(drain(frontend), 1)
    failures = [event.payload for event in observed if isinstance(event.payload, VoiceFrontendFailed)]
    assert [failure.error.code for failure in failures] == [VoiceErrorCode.CANCELLED]


async def test_single_reader_aclose_and_cancel_release_subscription_without_stopping_session():
    frontend = await started()
    reader = frontend.events()
    await anext(reader)
    competing = frontend.events()
    with pytest.raises(RuntimeError, match="one active reader"):
        await anext(competing)
    await reader.aclose()
    next_reader = frontend.events()
    await anext(next_reader)  # Remaining ACTIVE event.
    pending = asyncio.create_task(anext(next_reader))
    await asyncio.sleep(0)  # Enter empty-queue wait deterministically.
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert frontend.state == FrontendState.ACTIVE
    await frontend.stop(VoiceStopReason.USER, operation=operation("stop"))
    assert len(await asyncio.wait_for(drain(frontend), 1)) == 2


async def test_duplicate_late_and_out_of_order_transcript_events_retain_identity_for_reducer():
    frontend = await started()
    second_turn = replace(TURN, turn_id=VoiceTurnId("turn-two"), provider_input_id=ProviderInputId("input-two"), previous_provider_input_id=TURN.provider_input_id)
    opened_a = frontend.event(UserTurnOpened(None, VoiceActivitySource.PROVIDER), correlation=TURN)
    opened_b = frontend.event(UserTurnOpened(TURN.turn_id, VoiceActivitySource.PROVIDER), correlation=second_turn)
    final_b = frontend.event(UserTranscriptCommitted(VoiceTranscriptId("b"), "second", 1, UserCommitSource.PROVIDER), correlation=second_turn)
    final_a = frontend.event(UserTranscriptCommitted(VoiceTranscriptId("a"), "first", 1, UserCommitSource.PROVIDER), correlation=TURN)
    stale = replace(final_a, correlation=replace(TURN, session_id=VoiceSessionId("old-session")))
    for event in (opened_a, opened_b, final_b, final_a, final_b, stale):
        frontend.inject(event)
    await frontend.stop(VoiceStopReason.SWITCH, operation=operation("stop"))
    observed = (await drain(frontend))[2:-2]
    assert observed == [opened_a, opened_b, final_b, final_a, final_b, stale]
    assert final_b.correlation.previous_provider_input_id == final_a.correlation.provider_input_id
    with pytest.raises(RuntimeError, match="stopped"):
        frontend.inject(final_a)
    # Rejection of old-session operations is separate from deliberately injected
    # stale evidence. Task04 owns reducer deduplication/session filtering.
    fresh = await started()
    rejected = await fresh.append_spoken_result(VoiceTextUpdate("late"), operation=operation("late", stale.correlation))
    assert rejected.status == Status.REJECTED
    await fresh.stop(VoiceStopReason.USER, operation=operation("stop"))


async def test_live_style_fragments_do_not_imply_finality_alignment_or_task_text():
    frontend = await started()
    transcript = VoiceTranscriptId("revisable-group")
    fragment = replace(frontend.event(UserTranscriptDelta(transcript, "  unfinished ")), provider_interval=VoiceSessionInterval(12, 45))
    frontend.inject(fragment)
    frontend.inject(frontend.event(VoiceDelegationRequested(0), correlation=replace(SESSION, provider_delegation_id=ProviderDelegationId("opaque"))))
    frontend.inject(frontend.event(AssistantTranscriptDelta(VoiceTranscriptId("assistant"), "generated")))
    frontend.inject(frontend.event(AssistantPlaybackEvidence(VoicePlaybackStatus.PARTIAL, 12), correlation=OUTPUT))
    frontend.inject(frontend.event(UserInterruption(VoiceInterruptionStage.CANDIDATE, VoiceActivitySource.LOCAL), correlation=OUTPUT))
    await frontend.stop(VoiceStopReason.USER, operation=operation("stop"))
    observed = await drain(frontend)
    assert observed[2].payload.delta == "  unfinished "
    assert observed[2].provider_interval == VoiceSessionInterval(12, 45)
    assert observed[3].correlation.turn_id is None
    assert observed[5].payload.confirmed_text is None
    assert not any(isinstance(event.payload, (UserTranscriptCommitted, AssistantTranscriptCompleted, AssistantGenerationFinished)) for event in observed)


async def test_bounded_injection_reports_overflow_but_stop_still_terminates():
    frontend = await started(max_events=2)
    with pytest.raises(asyncio.QueueFull):
        frontend.inject(frontend.event(VoiceUsageUpdated(VoiceUsageSource.LOCAL_ESTIMATE)))
    await frontend.stop(VoiceStopReason.ERROR, operation=operation("stop"))
    assert len(await asyncio.wait_for(drain(frontend), 1)) == 4


@pytest.mark.parametrize("status,played,text", [
    (VoicePlaybackStatus.UNPLAYED, 0, "not heard"),
    (VoicePlaybackStatus.UNPLAYED, 2, None),
    (VoicePlaybackStatus.COMPLETE, 0, None),
    (VoicePlaybackStatus.PARTIAL, None, None),
    (VoicePlaybackStatus.UNKNOWN, 10, "unknown words"),
])
def test_playback_cannot_promote_unplayed_or_unknown_words(status, played, text):
    with pytest.raises(ValueError):
        AssistantPlaybackEvidence(status, played, text)


def test_completed_audio_can_retain_unknown_words_and_usage_absence_is_not_zero():
    assert AssistantPlaybackEvidence(VoicePlaybackStatus.COMPLETE, 100).confirmed_text is None
    assert VoiceUsageUpdated(VoiceUsageSource.PROVIDER_SNAPSHOT).duration_s is None
    assert VoiceUsageUpdated(VoiceUsageSource.LOCAL_ESTIMATE, 0).duration_s == 0


def test_results_enforce_diagnostics_and_never_false_stop():
    with pytest.raises(ValueError, match="diagnostics"):
        VoiceOperationResult(operation("unsupported"), Kind.CANCEL_SPEECH, Status.UNSUPPORTED, FrontendState.ACTIVE)
    with pytest.raises(ValueError, match="confirmed STOPPED"):
        VoiceOperationResult(operation("stop"), Kind.STOP, Status.COMPLETED, FrontendState.STOPPING)
    with pytest.raises(ValueError, match="Unknown stop"):
        VoiceOperationResult(operation("stop"), Kind.STOP, Status.UNKNOWN, FrontendState.STOPPED, VoiceFrontendError(VoiceErrorCode.CLOSE_UNCONFIRMED, Kind.STOP, FrontendState.STOPPED))


@pytest.mark.parametrize("make", [
    lambda: VoiceContext(revision=0.5),
    lambda: VoiceContext(messages=[VoiceContextMessage(VoiceContextRole.USER, "x")]),
    lambda: VoiceContext(messages=(VoiceContextMessage(VoiceContextRole.USER, "x"),) * 129),
    lambda: VoiceContext(messages=(VoiceContextMessage(VoiceContextRole.USER, "x" * 8192),) * 5),
    lambda: VoiceTextUpdate("x" * 8193),
    lambda: VoiceAudioChunk(b"\0"),
    lambda: VoiceAudioChunk(b"\0\0" * 24001),
    lambda: VoicePcmFormat(True),
    lambda: VoiceSessionInterval(2, 1),
    lambda: VoiceObservation(datetime(2026, 1, 1), 0),
    lambda: VoiceObservation(datetime(2026, 1, 1, tzinfo=timezone.utc), 0.5),
    lambda: VoiceUsageUpdated(VoiceUsageSource.PROVIDER_FINAL, float("nan")),
    lambda: VoiceUsageUpdated(VoiceUsageSource.PROVIDER_FINAL, input_tokens=1.5),
    lambda: UserTranscriptDelta(VoiceTranscriptId("x"), "text", True),
])
def test_invalid_boundary_values_fail_before_transport(make):
    with pytest.raises(ValueError):
        make()


def test_private_content_is_not_in_default_diagnostic_representations():
    secret = "private-conversation-fragment"
    values = [VoiceTextUpdate(secret), VoiceContextMessage(VoiceContextRole.USER, secret),
              AssistantTranscriptCompleted(VoiceTranscriptId("x"), secret),
              VoiceFrontendError(VoiceErrorCode.PROVIDER, None, FrontendState.ACTIVE, safe_message=secret)]
    assert all(secret not in repr(value) for value in values)
