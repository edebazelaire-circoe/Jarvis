from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from jarvis.core.voice_state import VoiceConversationState, VoiceStateDisposition as Disposition
from jarvis.domain.voice_events import (
    AssistantAudioChunk, AssistantGenerationFinished, AssistantPlaybackEvidence,
    AssistantSpeechActivity, AssistantTranscriptCompleted, AssistantTranscriptDelta,
    FrontendLifecycleChanged, UserCommitSource, UserInterruption, UserTranscriptCommitted,
    UserTranscriptDelta, UserTranscriptRevised, UserTurnOpened, VoiceActivitySource,
    VoiceDelegationRequested, VoiceFrontendFailed, VoiceGenerationStatus,
    VoiceInterruptionStage, VoicePlaybackStatus, VoiceSpeechPhase,
)
from jarvis.domain.voice_frontend import (
    FrontendState, ProviderOutputId, VoiceAudioChunk, VoiceCorrelation, VoiceErrorCode,
    VoiceFrontendError, VoiceSessionId, VoiceSpeechId, VoiceStopReason, VoiceTranscriptId,
    VoiceTurnId,
)
from jarvis.domain.voice_state import VoiceConversationSnapshot, VoiceSpeechState, VoiceTaskRecord
from jarvis.domain.work_state import WorkStatus
from tests.fakes.voice_frontend import FakeVoiceFrontend
from tests.unit.test_voice_frontend_contract import CONFIG, operation


SESSION = VoiceCorrelation(VoiceSessionId("session-a"))
TURN = replace(SESSION, turn_id=VoiceTurnId("turn-a"))
OUTPUT = replace(TURN, speech_id=VoiceSpeechId("speech-a"), provider_output_id=ProviderOutputId("output-a"))


class StateHarness:
    def __init__(self, **kwargs):
        self.state = VoiceConversationState("conversation", **kwargs)
        self.source = FakeVoiceFrontend()
        self.state.bind_session(SESSION.session_id)

    def event(self, payload, correlation=TURN):
        return self.source.event(payload, correlation=correlation)

    def apply(self, payload, correlation=TURN):
        result = self.state.apply(self.event(payload, correlation))
        assert result.disposition in (Disposition.APPLIED, Disposition.IGNORED), result
        assert not result.authorizes_actions
        return result

    def user(self, *, correlation=TURN, previous=None, text="user question"):
        self.apply(UserTurnOpened(previous, VoiceActivitySource.PROVIDER), correlation)
        self.apply(UserTranscriptCommitted(VoiceTranscriptId(correlation.turn_id), text, 1, UserCommitSource.PROVIDER), correlation)

    def speech(self, text="intended secret", correlation=OUTPUT):
        assert self.state.queue_speech(correlation, text).disposition == Disposition.APPLIED

    def generated(self, text="generated secret", correlation=OUTPUT):
        self.apply(AssistantTranscriptCompleted(VoiceTranscriptId("generated"), text), correlation)

    def heard(self, text=None, *, played=50, status=VoicePlaybackStatus.COMPLETE, correlation=OUTPUT):
        self.apply(AssistantPlaybackEvidence(status, played, text), correlation)


async def test_test_frontend_stream_drives_real_reducer_complete_conversation():
    frontend = FakeVoiceFrontend()
    state = VoiceConversationState("conversation")
    state.bind_session(SESSION.session_id)
    await frontend.start(CONFIG, operation=operation("start", SESSION))
    state.queue_speech(OUTPUT, "intended")
    for payload, correlation in (
        (UserTurnOpened(None, VoiceActivitySource.PROVIDER), TURN),
        (UserTranscriptDelta(VoiceTranscriptId("input"), "question", 0), TURN),
        (UserTranscriptCommitted(VoiceTranscriptId("input"), "question?", 1, UserCommitSource.PROVIDER), TURN),
        (AssistantTranscriptCompleted(VoiceTranscriptId("answer"), "paraphrase"), OUTPUT),
        (AssistantAudioChunk(VoiceAudioChunk(b"\0\0" * 1200)), OUTPUT),
        (AssistantGenerationFinished(VoiceGenerationStatus.COMPLETED), OUTPUT),
        (AssistantPlaybackEvidence(VoicePlaybackStatus.COMPLETE, 50, "paraphrase"), OUTPUT),
    ):
        frontend.inject(frontend.event(payload, correlation=correlation))
    await frontend.stop(VoiceStopReason.USER, operation=operation("stop", SESSION))
    results = []
    async def consume():
        async for event in frontend.events():
            results.append(state.apply(event))
    await asyncio.wait_for(consume(), 1)
    assert all(result.disposition in (Disposition.APPLIED, Disposition.IGNORED) for result in results)
    speech = state.snapshot.speeches[0]
    assert (speech.intended_text, speech.generated_text, speech.confirmed_text) == ("intended", "paraphrase", "paraphrase")
    assert speech.state == VoiceSpeechState.COMPLETE
    assert [message.text for message in state.recent_context().messages] == ["question?", "paraphrase"]
    encoded = json.dumps(state.snapshot.to_dict())
    assert "pcm" not in encoded and "monotonic" not in encoded
    assert speech.received_audio_ms == 50


def test_generated_text_before_audio_never_becomes_heard_or_completed_speech():
    h = StateHarness()
    h.user()
    h.speech()
    h.generated()
    assert h.state.snapshot.speeches[0].confirmed_text is None
    assert [m.text for m in h.state.recent_context().messages] == ["user question"]
    h.apply(AssistantAudioChunk(VoiceAudioChunk(b"\0\0" * 1200)), OUTPUT)
    h.apply(AssistantGenerationFinished(VoiceGenerationStatus.COMPLETED), OUTPUT)
    assert h.state.snapshot.speeches[0].state != VoiceSpeechState.COMPLETE
    h.heard("actual words")
    speech = h.state.snapshot.speeches[0]
    assert (speech.intended_text, speech.generated_text, speech.confirmed_text) == ("intended secret", "generated secret", "actual words")


def test_partial_unknown_alignment_and_late_generated_tail_remain_distinct():
    h = StateHarness()
    h.user()
    h.speech()
    h.apply(AssistantTranscriptDelta(VoiceTranscriptId("generated"), "prefix "), OUTPUT)
    h.apply(AssistantSpeechActivity(VoiceSpeechPhase.STARTED), OUTPUT)
    h.heard(played=20, status=VoicePlaybackStatus.PARTIAL)
    h.apply(UserInterruption(VoiceInterruptionStage.CONFIRMED, VoiceActivitySource.LOCAL), OUTPUT)
    h.apply(AssistantSpeechActivity(VoiceSpeechPhase.STOPPED), OUTPUT)
    h.generated("prefix and unplayed tail")
    h.apply(AssistantGenerationFinished(VoiceGenerationStatus.CANCELLED), OUTPUT)
    speech = h.state.snapshot.speeches[0]
    assert speech.state == VoiceSpeechState.INTERRUPTED
    assert speech.played_ms == 20 and speech.confirmed_text is None
    restored = VoiceConversationSnapshot.from_dict(json.loads(json.dumps(h.state.snapshot.to_dict())))
    assert restored.speeches[0].confirmed_text is None
    assert [m.text for m in h.state.recent_context().messages] == ["user question"]


def test_cumulative_confirmation_is_replaced_not_appended_and_never_regresses():
    h = StateHarness()
    h.user()
    h.speech()
    h.heard("heard", played=20, status=VoicePlaybackStatus.PARTIAL)
    h.heard("heard more", played=30, status=VoicePlaybackStatus.PARTIAL)
    h.heard(None, played=40, status=VoicePlaybackStatus.PARTIAL)
    assert h.state.snapshot.speeches[0].confirmed_text == "heard more"
    before = h.state.snapshot
    result = h.state.apply(h.event(AssistantPlaybackEvidence(VoicePlaybackStatus.UNPLAYED, 0), OUTPUT))
    assert result.code == "voice_state_playback_regression"
    assert h.state.snapshot == before
    h.heard(None, played=40, status=VoicePlaybackStatus.COMPLETE)
    assert h.state.snapshot.speeches[0].confirmed_text == "heard more"
    assert [m.text for m in h.state.recent_context().messages][-1] == "heard more"


def test_zero_played_cancelled_output_cannot_be_promoted_by_late_generation_completion():
    h = StateHarness()
    h.user()
    h.speech()
    h.apply(UserInterruption(VoiceInterruptionStage.CONFIRMED, VoiceActivitySource.LOCAL), OUTPUT)
    h.generated("never played")
    h.apply(AssistantGenerationFinished(VoiceGenerationStatus.COMPLETED), OUTPUT)
    speech = h.state.snapshot.speeches[0]
    assert speech.state == VoiceSpeechState.CANCELLED and speech.confirmed_text is None
    assert len(h.state.recent_context().messages) == 1


def test_valid_late_playback_after_new_user_turn_is_retained_in_heard_chronology():
    h = StateHarness()
    h.user(text="first question")
    h.speech()
    second = replace(TURN, turn_id=VoiceTurnId("turn-b"))
    h.user(correlation=second, previous=TURN.turn_id, text="new question")
    h.apply(UserInterruption(VoiceInterruptionStage.CONFIRMED, VoiceActivitySource.LOCAL), OUTPUT)
    h.generated("late generated tail")
    h.heard("independently confirmed earlier words", played=20, status=VoicePlaybackStatus.PARTIAL)
    assert h.state.snapshot.active_turn_id == second.turn_id
    assert h.state.snapshot.speeches[0].state == VoiceSpeechState.INTERRUPTED
    assert [m.text for m in h.state.recent_context().messages] == ["first question", "new question", "independently confirmed earlier words"]


def test_asr_final_b_before_a_cannot_replace_active_intent_or_input_order():
    h = StateHarness()
    second = replace(TURN, turn_id=VoiceTurnId("turn-b"))
    h.apply(UserTurnOpened(None, VoiceActivitySource.PROVIDER))
    h.apply(UserTurnOpened(TURN.turn_id, VoiceActivitySource.PROVIDER), second)
    h.apply(UserTranscriptCommitted(VoiceTranscriptId("b"), "second intent", 2, UserCommitSource.PROVIDER), second)
    h.apply(UserTranscriptCommitted(VoiceTranscriptId("a"), "first intent", 1, UserCommitSource.PROVIDER))
    assert h.state.snapshot.active_turn_id == second.turn_id
    assert [m.text for m in h.state.recent_context().messages] == ["first intent", "second intent"]


def test_append_revision_and_explicit_provisional_replacement_never_authorize_work():
    h = StateHarness()
    h.apply(UserTurnOpened(None, VoiceActivitySource.LOCAL))
    transcript = VoiceTranscriptId("provisional")
    h.apply(UserTranscriptDelta(transcript, "book ", 0))
    h.apply(UserTranscriptDelta(transcript, "flight", 1))
    assert h.state.snapshot.users[0].text == "book flight"
    h.apply(UserTranscriptRevised(transcript, "do not book", 2))
    assert h.state.snapshot.users[0].text == "do not book"
    stale = h.state.apply(h.event(UserTranscriptDelta(transcript, "late", 1)))
    assert stale.disposition == Disposition.STALE
    h.apply(VoiceDelegationRequested(2))
    assert h.state.snapshot.tasks == ()
    result = h.state.update_task(VoiceTaskRecord("task", TURN.turn_id, WorkStatus.RUNNING, 0))
    assert result.code == "voice_state_committed_source_required"
    assert not result.authorizes_actions and not h.state.snapshot.authorizes_actions
    h.apply(UserTranscriptCommitted(transcript, "do not book anything", 3, UserCommitSource.APPLICATION))
    assert h.state.snapshot.users[0].committed
    late = h.state.apply(h.event(UserTranscriptRevised(transcript, "book now", 4)))
    assert late.code == "voice_state_turn_already_committed"


def test_snapshot_roundtrip_preserves_task_results_candidates_and_session_replacement():
    h = StateHarness()
    h.user()
    task = VoiceTaskRecord("task", TURN.turn_id, WorkStatus.RUNNING, 0, "working summary")
    assert h.state.update_task(task).disposition == Disposition.APPLIED
    h.speech(correlation=replace(OUTPUT, task_id="task"))
    h.generated()
    h.heard("heard words", status=VoicePlaybackStatus.PARTIAL)
    encoded = json.loads(json.dumps(h.state.snapshot.to_dict()))
    restored = VoiceConversationSnapshot.from_dict(encoded)
    assert restored == h.state.snapshot
    resumed = VoiceConversationState.from_snapshot(restored)
    assert resumed.last_monotonic_ns is None
    assert resumed.snapshot.speeches[0].confirmed_text == "heard words"
    assert resumed.bind_session("session-b").disposition == Disposition.APPLIED
    assert resumed.snapshot.tasks == (task,)
    assert resumed.snapshot.users == h.state.snapshot.users
    result = resumed.update_task(replace(task, status=WorkStatus.COMPLETED, revision=1, result="backend facts"))
    assert result.disposition == Disposition.APPLIED
    assert resumed.snapshot.tasks[0].result == "backend facts"
    assert "backend facts" not in [m.text for m in resumed.recent_context().messages]
    assert resumed.snapshot.speeches[0].confirmed_text == "heard words"
    stale = resumed.apply(h.event(AssistantPlaybackEvidence(VoicePlaybackStatus.COMPLETE, 100, "old session tail"), OUTPUT))
    assert stale.disposition == Disposition.STALE_SESSION
    assert resumed.snapshot.speeches[0].confirmed_text == "heard words"


def test_active_session_rehydrate_requires_cleanup_before_rebinding():
    h = StateHarness()
    h.apply(FrontendLifecycleChanged(FrontendState.STARTING), SESSION)
    h.apply(FrontendLifecycleChanged(FrontendState.ACTIVE), SESSION)
    resumed = VoiceConversationState.from_snapshot(h.state.snapshot)
    assert resumed.snapshot.lifecycle == FrontendState.UNKNOWN_REAP_REQUIRED
    assert resumed.bind_session("session-b").code == "voice_state_close_required"


def test_snapshot_defensive_copies_and_frozen_values():
    h = StateHarness()
    h.user()
    h.speech()
    h.generated()
    original = h.state.snapshot
    encoded = original.to_dict()
    decoded = VoiceConversationSnapshot.from_dict(encoded)
    encoded["users"][0]["text"] = "mutated"
    encoded["speeches"][0]["generated"][0]["text"] = "mutated"
    assert decoded == original
    with pytest.raises(FrozenInstanceError):
        original.users[0].text = "mutated"


def test_bounded_deduplication_rejects_expired_replay_and_counter_conflicts():
    h = StateHarness(max_seen_events=2)
    first = h.event(VoiceDelegationRequested(0))
    assert h.state.apply(first).disposition == Disposition.IGNORED
    assert h.state.apply(first).disposition == Disposition.DUPLICATE
    collision = replace(first, event_id="different-event")
    assert h.state.apply(collision).code == "voice_state_sequence_conflict"
    h.apply(VoiceDelegationRequested(0))
    h.apply(VoiceDelegationRequested(0))
    assert len(h.state.snapshot.seen_events) == 2
    assert h.state.apply(first).code == "voice_state_replay_expired"
    snapshot = VoiceConversationSnapshot.from_dict(json.loads(json.dumps(h.state.snapshot.to_dict())))
    assert VoiceConversationState.from_snapshot(snapshot).apply(first).disposition == Disposition.STALE


def test_retention_preserves_active_task_turn_and_rejects_full_active_candidate_capacity():
    h = StateHarness(max_users=2, max_speeches=1, max_tasks=1)
    h.user()
    task = VoiceTaskRecord("task", TURN.turn_id, WorkStatus.RUNNING, 0)
    h.state.update_task(task)
    second = replace(TURN, turn_id=VoiceTurnId("turn-b"))
    third = replace(TURN, turn_id=VoiceTurnId("turn-c"))
    h.user(correlation=second, previous=TURN.turn_id)
    h.user(correlation=third, previous=second.turn_id)
    assert {u.correlation.turn_id for u in h.state.snapshot.users} == {TURN.turn_id, third.turn_id}
    assert h.state.snapshot.tasks == (task,)
    h.speech()
    result = h.state.queue_speech(replace(OUTPUT, speech_id="another", provider_output_id="another"), "pending")
    assert result.disposition == Disposition.CAPACITY
    assert len(h.state.snapshot.speeches) == 1
    full = h.state.update_task(VoiceTaskRecord("another-task", third.turn_id, WorkStatus.RUNNING, 0))
    assert full.disposition == Disposition.CAPACITY
    assert h.state.snapshot.tasks == (task,)


def test_terminal_silent_generation_is_unheard_and_evictable():
    h = StateHarness(max_speeches=1)
    h.speech()
    h.generated("tool only text")
    h.apply(AssistantGenerationFinished(VoiceGenerationStatus.COMPLETED), OUTPUT)
    assert h.state.snapshot.speeches[0].state == VoiceSpeechState.UNSPOKEN
    assert h.state.snapshot.speeches[0].confirmed_text is None
    assert h.state.queue_speech(replace(OUTPUT, speech_id="next", provider_output_id="next"), "next").disposition == Disposition.APPLIED


def test_terminal_task_cannot_reopen_and_result_does_not_queue_speech():
    h = StateHarness()
    h.user()
    task = VoiceTaskRecord("task", TURN.turn_id, WorkStatus.COMPLETED, 1, result="facts")
    h.state.update_task(task)
    assert h.state.snapshot.speeches == ()
    assert h.state.update_task(replace(task, revision=2, status=WorkStatus.RUNNING)).code == "voice_state_task_transition_invalid"


def test_late_confirmation_cannot_replace_or_erase_known_heard_prefix():
    h = StateHarness()
    h.speech()
    h.heard("confirmed prefix", played=20, status=VoicePlaybackStatus.PARTIAL)
    before = h.state.snapshot
    event = h.event(AssistantPlaybackEvidence(VoicePlaybackStatus.COMPLETE, 40, "different generated tail"), OUTPUT)
    assert h.state.apply(event).code == "voice_state_confirmation_regression"
    assert h.state.snapshot == before


def test_out_of_order_observed_turn_boundaries_are_reconciled_without_cycles():
    h = StateHarness()
    second = replace(TURN, turn_id="turn-b")
    h.apply(UserTurnOpened(TURN.turn_id, VoiceActivitySource.PROVIDER), second)
    h.apply(UserTurnOpened(None, VoiceActivitySource.PROVIDER), TURN)
    assert h.state.snapshot.active_turn_id == second.turn_id
    h.apply(UserTranscriptCommitted("b", "second", 1, UserCommitSource.PROVIDER), second)
    h.apply(UserTranscriptCommitted("a", "first", 1, UserCommitSource.PROVIDER), TURN)
    assert [m.text for m in h.state.recent_context().messages] == ["first", "second"]
    result = h.state.apply(h.event(UserTurnOpened(second.turn_id, VoiceActivitySource.PROVIDER), TURN))
    assert result.code == "voice_state_turn_order_conflict"


def test_unknown_playback_can_remain_unknown_without_fabricated_zero_or_words():
    h = StateHarness()
    h.speech()
    h.apply(AssistantPlaybackEvidence(VoicePlaybackStatus.UNKNOWN, None), OUTPUT)
    assert h.state.snapshot.speeches[0].played_ms is None
    assert h.state.snapshot.speeches[0].confirmed_text is None
    assert VoiceConversationSnapshot.from_dict(json.loads(json.dumps(h.state.snapshot.to_dict()))) == h.state.snapshot


def test_same_turn_cannot_be_committed_twice_under_distinct_transcript_ids():
    h = StateHarness()
    h.user()
    before = h.state.snapshot
    result = h.state.apply(h.event(UserTranscriptCommitted("another-transcript", "different text", 2, UserCommitSource.PROVIDER)))
    assert result.disposition == Disposition.REJECTED
    assert h.state.snapshot == before


def test_invalid_identity_is_not_copied_to_diagnostic_output(tmp_path):
    from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

    journal = RuntimeJournal(tmp_path)
    h = StateHarness(diagnostics=journal)
    invalid = replace(TURN, turn_id="PRIVATE_INVALID\nIDENTITY")
    result = h.state.apply(h.event(VoiceDelegationRequested(0), invalid))
    assert result.disposition == Disposition.REJECTED
    assert "PRIVATE_INVALID" not in json.dumps(read_jsonl_tail(journal.trace_path))


def test_closed_frontend_cannot_resurrect_activity_but_can_receive_historical_playback():
    from jarvis.domain.voice_events import AssistantGenerationStarted

    h = StateHarness()
    h.user()
    h.speech()
    h.apply(FrontendLifecycleChanged(FrontendState.STOPPED), SESSION)
    assert not h.state.snapshot.speeches[0].active
    for payload in (AssistantGenerationStarted(), AssistantSpeechActivity(VoiceSpeechPhase.STARTED)):
        result = h.state.apply(h.event(payload, OUTPUT))
        assert result.code == "voice_state_frontend_closed"
    new_output = replace(OUTPUT, speech_id="late-speech", provider_output_id="late-output")
    assert h.state.queue_speech(new_output, "late result").code == "voice_state_frontend_closed"
    h.generated("late generated but unplayed", correlation=new_output)
    assert not h.state.snapshot.speeches[-1].active
    h.heard("actual historic words", correlation=OUTPUT)
    assert h.state.snapshot.speeches[0].confirmed_text == "actual historic words"
    assert not any(s.active for s in h.state.snapshot.speeches)


def test_complete_playback_after_interruption_does_not_promote_unknown_generated_tail():
    h = StateHarness()
    h.user()
    h.speech()
    h.generated("heard prefix and an unplayed tail")
    h.heard("heard prefix", played=20, status=VoicePlaybackStatus.PARTIAL)
    h.apply(UserInterruption(VoiceInterruptionStage.CONFIRMED, VoiceActivitySource.LOCAL), OUTPUT)
    h.heard(None, played=20, status=VoicePlaybackStatus.COMPLETE)
    speech = h.state.snapshot.speeches[0]
    assert speech.state == VoiceSpeechState.INTERRUPTED
    assert speech.playback_status == VoicePlaybackStatus.COMPLETE
    assert speech.confirmed_text == "heard prefix"
    assert [message.text for message in h.state.recent_context().messages] == ["user question", "heard prefix"]


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema_version=True),
    lambda d: d.update(schema_version=2),
    lambda d: d.update(revision=0.5),
    lambda d: d.update(current_session_id=""),
    lambda d: d.update(lifecycle="made-up"),
    lambda d: d.update(extra="provider data"),
    lambda d: d.update(last_observed_at="2026-01-01T00:00:00"),
    lambda d: d["users"][0].update(committed=1),
    lambda d: d["users"][0]["correlation"].update(session_id=[]),
    lambda d: d["users"][0].update(text="x" * 8193),
    lambda d: d["users"].append(d["users"][0]),
    lambda d: d["speeches"][0].update(played_ms=float("nan")),
    lambda d: d["speeches"][0].update(played_ms=-1),
    lambda d: d["speeches"][0].update(confirmed_text="unheard"),
    lambda d: d["speeches"][0].update(state="complete"),
    lambda d: d["turns"][0].update(previous_turn_id=TURN.turn_id),
    lambda d: d.update(active_turn_id="missing"),
    lambda d: d["tasks"][0].update(source_turn_id="missing"),
    lambda d: d["tasks"][0].update(status="unauthorized"),
    lambda d: d["seen_events"][0].update(sequence=True),
])
def test_snapshot_rejects_malformed_versions_types_ids_and_evidence(mutate):
    h = StateHarness()
    h.user()
    h.speech()
    h.state.update_task(VoiceTaskRecord("task", TURN.turn_id, WorkStatus.RUNNING, 0))
    payload = json.loads(json.dumps(h.state.snapshot.to_dict()))
    mutate(payload)
    with pytest.raises((ValueError, TypeError)):
        VoiceConversationSnapshot.from_dict(payload)


def test_runtime_journal_records_safe_normal_drop_divergence_and_failure_evidence(tmp_path):
    from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

    journal = RuntimeJournal(tmp_path)
    h = StateHarness(diagnostics=journal, max_speeches=1)
    h.user(text="PRIVATE_USER")
    h.speech("PRIVATE_INTENT")
    h.generated("PRIVATE_GENERATED")
    stale = h.event(VoiceDelegationRequested(0), replace(SESSION, session_id="other-session"))
    assert h.state.apply(stale).disposition == Disposition.STALE_SESSION
    h.state.queue_speech(replace(OUTPUT, speech_id="full", provider_output_id="full"), "PRIVATE_CANDIDATE")
    h.heard("PRIVATE_SPOKEN")
    h.apply(VoiceFrontendFailed(VoiceFrontendError(VoiceErrorCode.TRANSPORT, None, FrontendState.ACTIVE, safe_message="PRIVATE_EXCEPTION")), SESSION)
    rows = read_jsonl_tail(journal.trace_path)
    assert any(row["kind"] == "voice.state.diverged" and row["level"] == "info" for row in rows)
    assert any(row["kind"] == "voice.state.spoken_diverged" and row["level"] == "info" for row in rows)
    assert any(row["data"]["code"] == "voice_state_stale_session" and row["level"] == "info" for row in rows)
    assert any(row["data"]["code"] == "voice_state_capacity" and row["level"] == "warning" for row in rows)
    assert [row["data"]["code"] for row in read_jsonl_tail(journal.error_path)] == [VoiceErrorCode.TRANSPORT.value]
    assert "PRIVATE_" not in json.dumps(rows)
    assert all("revision" in row["data"] and "session_id" in row["data"] for row in rows)
