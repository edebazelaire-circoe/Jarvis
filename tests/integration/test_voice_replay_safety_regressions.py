"""Incident fixtures drive production safety seams, without acoustics or providers.

Tags and timing are reconstructed evidence, not recordings. The timeout adapter
only releases an asyncio deadline; it contains no scheduler or interruption policy.
"""
from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from jarvis.core.voice_state import VoiceConversationState, VoiceStateDisposition
from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
from jarvis.domain.v2 import ProtocolEnvelope, SpeechKind, SpeechRequest, VoiceLifecycleState
from jarvis.domain.voice_events import (
    AssistantGenerationFinished, AssistantPlaybackEvidence, AssistantSpeechActivity,
    AssistantTranscriptCompleted, FrontendLifecycleChanged, UserCommitSource,
    UserInterruption, UserTranscriptCommitted, UserTurnOpened, VoiceActivitySource,
    VoiceGenerationStatus, VoiceInterruptionStage, VoicePlaybackStatus, VoiceSpeechPhase,
)
from jarvis.domain.voice_frontend import FrontendState, VoiceCorrelation, VoiceObservation
from jarvis.domain.voice_state import VoiceSpeechState, VoiceTaskRecord
from jarvis.domain.work_state import WorkStatus
from jarvis.runtime import speech_scheduler as scheduler_module
from jarvis.runtime.voice_metrics import VoiceSessionMetricRecorder
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture
from tests.fakes.speech_context import source
from tests.fakes.voice_frontend import FakeVoiceFrontend
from tests.replay.voice_replay import ReplayClock, ReplayDriver, load_replay_fixture
from tests.unit.test_v2_speech_scheduler import FakeCore, FakeVoiceSession, build_scheduler
from tests.unit.test_v2_voice_toggle import FakeHttpSession, FakeWakeWord, FakeWebSocket
from tests.unit.test_voice_duplex import (
    ControllableSession, GuardedAudio, RecordingCore, RecordingJournal, build_bridge,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "voice_replay"
SESSION = "replay-session"


def replay(name):
    fixture = load_replay_fixture(FIXTURES / f"{name}.json")
    clock = ReplayClock(fixture.origin, monotonic_start=10)
    return fixture, clock, ReplayDriver(clock)


class MetricJournal(RecordingJournal):
    """Capture real emitted diagnostics with the replay's observation clock."""

    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.recorder = None

    def emit(self, kind, message, *, level="info", data=None):
        super().emit(kind, message, level=level, data=data)
        if self.recorder is not None:
            self.recorder.observe({**self.events[-1], "ts": self.clock.now().isoformat()})


def metrics(tmp_path, clock, journal, conversation):
    recorder = VoiceSessionMetricRecorder(
        runtime_root=tmp_path, journal=journal, architecture="replay", provider_id="fixture",
        model_id="fixture", configuration_id="safety-replay", clock=clock.monotonic,
        wall_clock=clock.now,
    )
    recorder.start(conversation_id=conversation, session_id=SESSION)
    journal.recorder = recorder
    return recorder


class CanonicalEvidence:
    def __init__(self, clock, journal, conversation="conversation-1"):
        self.clock = clock
        self.frontend = FakeVoiceFrontend()
        self.state = VoiceConversationState(conversation, diagnostics=journal)
        self.state.bind_session(SESSION)
        self.turn = VoiceCorrelation(SESSION, turn_id="source-turn")
        self.apply(UserTurnOpened(None, VoiceActivitySource.PROVIDER), self.turn)
        self.apply(UserTranscriptCommitted("input", "source request", 1, UserCommitSource.PROVIDER), self.turn)

    def apply(self, payload, correlation):
        event = self.frontend.event(payload, correlation=correlation)
        event = replace(event, observation=VoiceObservation(self.clock.now(), self.clock.monotonic_ns()))
        result = self.state.apply(event)
        assert result.disposition in (VoiceStateDisposition.APPLIED, VoiceStateDisposition.IGNORED)
        return result


async def test_spoken_divergence_preserves_intended_generated_and_heard_evidence(tmp_path):
    fixture, clock, driver = replay("spoken_divergence")
    journal = MetricJournal(clock)
    recorder = metrics(tmp_path, clock, journal, "conversation-1")
    evidence = CanonicalEvidence(clock, journal)
    correlation = replace(evidence.turn, speech_id="candidate-a", provider_output_id="output-a")
    results = {}
    generated = {}

    def ready(step):
        results[step.data["work_id"]] = step.data["result_tag"]

    def enqueue(step):
        result = evidence.state.queue_speech(correlation, results[step.data["work_id"]])
        assert result.disposition is VoiceStateDisposition.APPLIED

    def transcript(step):
        generated[step.data["output_id"]] = step.data["generated_tag"]
        evidence.apply(AssistantTranscriptCompleted("generated", step.data["generated_tag"]), correlation)
        assert evidence.state.snapshot.speeches[0].confirmed_text is None

    def consume(step):
        # A local device proof is independently supplied; generation alone cannot do this.
        evidence.apply(AssistantPlaybackEvidence(VoicePlaybackStatus.COMPLETE,
                       step.data["played_ms"], generated[step.data["output_id"]]), correlation)

    await driver.run(fixture, {
        "brain.ready": ready, "scheduler.enqueue": enqueue,
        "provider.output_started": lambda step: evidence.apply(AssistantSpeechActivity(VoiceSpeechPhase.STARTED), correlation),
        "provider.transcript_final": transcript, "device.consume": consume,
        "provider.output_done": lambda step: evidence.apply(AssistantGenerationFinished(VoiceGenerationStatus.COMPLETED), correlation),
    })
    speech = evidence.state.snapshot.speeches[0]
    assert (speech.intended_text, speech.generated_text, speech.confirmed_text) == ("intended-a", "actual-b", "actual-b")
    assert speech.state is VoiceSpeechState.COMPLETE
    assert [message.text for message in evidence.state.recent_context().messages] == ["source request", "actual-b"]
    report = recorder.finish(status="stopped")
    assert report["event_counts"]["intended_spoken_divergence"] == 1
    assert journal.count("voice.state.spoken_diverged") == 1


async def test_bus_cluster_seven_rejections_never_stop_duck_cancel_or_submit_work(tmp_path):
    fixture, clock, driver = replay("bus_cluster_7")
    audio, session, core = GuardedAudio(guarded=True, gate_open=True), ControllableSession(), RecordingCore()
    session.session_id = SESSION
    journal = MetricJournal(clock)
    recorder = metrics(tmp_path, clock, journal, "conv-duplex")
    bridge = build_bridge(audio, session=session, core=core, journal=journal, clock=clock.monotonic,
                          barge_in_confirm_s=3600)
    tokens = {}

    async def candidate(step):
        await bridge._on_near_end()
        tokens[step.data["candidate_id"]] = bridge._barge_pending_token

    await driver.run(fixture, {
        "provider.output_started": lambda step: bridge._handle_event(ProtocolEnvelope(message_type="realtime.output_started", payload=dict(step.data))),
        "owner.candidate": candidate,
        "owner.rejected": lambda step: bridge._on_barge_timeout(tokens[step.data["candidate_id"]]),
    })
    assert journal.count("voice.barge_in_pending") == journal.count("voice.barge_in_rejected") == 7
    assert audio.stop_output_calls == 0 and audio.gains == []
    assert session.calls == [] and core.brain_turns == [] and core.turns == []
    assert bridge._playing and not bridge._barge_pending
    assert recorder.finish(status="stopped")["event_counts"]["false_or_rejected_barge_in"] == 7


async def test_confirmed_interrupt_without_provider_item_never_invents_heard_words():
    fixture, clock, driver = replay("confirmed_interrupt_missing_item")
    journal = MetricJournal(clock)
    audio, wire = GuardedAudio(guarded=True, gate_open=True), FakeWebSocket()
    session = OpenAIRealtimeSession(wire, FakeHttpSession(wire), owns_http=False)
    evidence = CanonicalEvidence(clock, journal, "conv-duplex")
    correlation = replace(evidence.turn, speech_id="local-playback")
    evidence.state.queue_speech(correlation, "unplayed words")
    bridge = build_bridge(audio, session=session, journal=journal, clock=clock.monotonic,
                          barge_in_confirm_s=3600)

    async def busy(step):
        await bridge._handle_event(ProtocolEnvelope(message_type="realtime.output_started",
                                  payload={"output_id": step.data["playback_id"]}))

    async def confirm(step):
        assert step.data["provider_item_id"] is None and step.data["played_ms"] == 0
        await bridge._barge_in()
        evidence.apply(UserInterruption(VoiceInterruptionStage.CONFIRMED, VoiceActivitySource.LOCAL), correlation)

    def checkpoint(step):
        assert step.data["checkpoint_id"] == "interrupt_applied"
        assert audio.stop_output_calls == 1 and not bridge._playing
        data = journal.of("voice.barge_in")[0]["data"]
        assert data["provider_item_id"] is None and data["played_ms"] == 0
        assert journal.of("voice.barge_in_degraded")[-1]["data"]["code"] == "barge_in_truncate_failed"
        assert not any(row["type"] == "conversation.item.truncate" for row in wire.sent)
        speech = evidence.state.snapshot.speeches[0]
        assert speech.state is VoiceSpeechState.CANCELLED and speech.confirmed_text is None
        assert [message.text for message in evidence.state.recent_context().messages] == ["source request"]

    await driver.run(fixture, {"device.output_busy": busy, "owner.candidate": lambda step: bridge._on_near_end(),
                              "owner.confirmed": confirm, "control.checkpoint": checkpoint})


async def test_late_provider_cancel_rejection_keeps_local_stop_and_drops_late_pcm():
    fixture, clock, driver = replay("provider_cancel_after_generation")
    audio, session, core, journal = GuardedAudio(), ControllableSession(), RecordingCore(), MetricJournal(clock)
    bridge = build_bridge(audio, session=session, core=core, journal=journal, clock=clock.monotonic)

    async def busy(step):
        await audio.play_b64(base64.b64encode(b"\1\0" * 163200).decode())

    async def confirm(step):
        assert step.data["played_ms"] == 6800
        await bridge._barge_in()
        assert audio.stop_output_calls == 1 and not bridge._playing

    async def reject(step):
        assert step.data["reason_code"] == "no_active_response"
        stopped = await bridge._handle_event(ProtocolEnvelope(message_type="realtime.error",
                    payload={"error": {"code": "response_cancel_not_active", "message": "no active response"}}))
        assert stopped is False

    async def release(step):
        before = audio.written_output_ms
        await bridge._play_audio(1, ProtocolEnvelope(message_type="realtime.audio", payload={
            "output_id": step.data["output_id"], "pcm_b64": base64.b64encode(b"\1\0" * 2400).decode()}))
        assert audio.written_output_ms == before
        bridge._release_playback_output(ProtocolEnvelope(message_type="realtime.response_done", payload={"output_id": step.data["output_id"]}))

    await driver.run(fixture, {
        "provider.output_started": lambda step: bridge._handle_event(ProtocolEnvelope(message_type="realtime.output_started", payload=dict(step.data))),
        "device.output_busy": busy, "owner.confirmed": confirm,
        "provider.cancel_rejected": reject, "device.release": release,
    })
    assert session.calls.count("cancel_output") == 1 and audio.stop_output_calls == 1
    assert journal.of("voice.barge_in_degraded")[-1]["data"]["code"] == "response_cancel_not_active"
    assert core.brain_turns == [] and core.turns == []


async def test_missing_terminal_recovers_at_replay_deadline_and_next_output_speaks(tmp_path, monkeypatch):
    fixture, clock, driver = replay("missing_terminal_stall")
    core, session, journal = FakeCore(), FakeVoiceSession(), MetricJournal(clock)
    session.session_id = SESSION
    recorder = metrics(tmp_path, clock, journal, "conversation-1")
    scheduler = build_scheduler(core, session, journal=journal, clock=clock, output_timeout_s=30)
    entered, expiry = asyncio.Event(), asyncio.Event()
    first = True

    async def controlled_wait(awaitable, timeout):
        nonlocal first
        if first and timeout == 30:
            first = False
            entered.set()
            try:
                await expiry.wait()
            finally:
                awaitable.close()
            raise TimeoutError
        return await asyncio.wait_for(awaitable, timeout)

    proxy = SimpleNamespace(**{name: getattr(asyncio, name) for name in dir(asyncio)})
    proxy.wait_for = controlled_wait
    monkeypatch.setattr(scheduler_module, "asyncio", proxy)
    tasks = []

    def request(identity, text):
        return SpeechRequest(conversation_id="conversation-1", text=text, id=identity,
                             kind=SpeechKind.RESULT, created_at=clock.now(), correlation_id="corr-1", source=source())

    async def started(step):
        task = asyncio.create_task(scheduler._speak(request(step.data["output_id"], "unconfirmed")))
        tasks.append(task)
        await asyncio.wait_for(entered.wait(), 1)
        await scheduler.note_output_event(ProtocolEnvelope(message_type="realtime.output_started",
                                             payload={"output_id": session.active_output_id}))

    async def release(step):
        assert step.data["provider_still_active"] is False and clock.elapsed_ms == 30000
        session.active_output_id = None
        session.live_speaks = 0
        expiry.set()
        await asyncio.wait_for(tasks[0], 1)

    async def checkpoint(step):
        assert core.turns == [] and journal.count("voice.speech.completed") == 0
        assert journal.of("voice.speech.output_stalled")[0]["data"]["still_active"] is False
        assert journal.of("voice.speech.interrupted")[0]["data"]["status"] == "unknown"
        original = session.speak_reserved

        async def complete(request, *, output_id):
            await original(request, output_id=output_id)
            session.active_output_id = None
            await scheduler.note_output_event(ProtocolEnvelope(message_type="realtime.response_done", payload={"output_id": output_id, "status": "completed"}))
            return output_id

        session.speak_reserved = complete
        await scheduler._speak(request("next-output", "next answer"))
        assert session.texts() == ["unconfirmed", "next answer"]
        assert [turn["content"] for turn in core.turns] == ["next answer"]

    try:
        await driver.run(fixture, {"provider.output_started": started, "device.release": release,
                                  "control.checkpoint": checkpoint})
    finally:
        expiry.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await scheduler.stop()
    report = recorder.finish(status="stopped")
    assert report["event_counts"]["output_stall"] == 1
    assert report["event_counts"]["intended_spoken_divergence"] == 0
    assert report["session_duration_seconds"] == 30
    assert journal.count("voice.speech.output_stalled") == 1
    assert journal.count("voice.speech.completed") == 1


async def test_manual_close_retains_late_core_results_without_speech_and_reports_once(tmp_path):
    fixture, clock, driver = replay("manual_close_late_results")
    journal = MetricJournal(clock)
    recorder = metrics(tmp_path, clock, journal, "conversation-1")
    evidence = CanonicalEvidence(clock, journal)
    core, session = FakeCore(), FakeVoiceSession()
    session.session_id = SESSION
    scheduler = build_scheduler(core, session, journal=journal, clock=clock)
    close_calls = []
    original_close = session.close

    async def close():
        close_calls.append(clock.elapsed_ms)
        await original_close()

    session.close = close

    async def factory(context):
        raise AssertionError("manual close must not reopen a provider")

    runtime = PersistentVoiceRuntime(wakeword=FakeWakeWord(), core=core, realtime_factory=factory,
                                    voice_arch=VoiceArchitecture.LEGACY, journal=journal)
    runtime._session, runtime._speech, runtime._metrics = session, scheduler, recorder
    runtime.runtime.state = VoiceLifecycleState.ACTIVE
    for identity in ("late-work-1", "late-work-2"):
        assert evidence.state.update_task(VoiceTaskRecord(identity, "source-turn", WorkStatus.RUNNING, 0)).disposition is VoiceStateDisposition.APPLIED

    async def started(step):
        await scheduler.note_output_event(ProtocolEnvelope(message_type="realtime.output_started", payload=dict(step.data)))

    def busy(step):
        session.active_output_id = step.data["output_id"]

    async def closed(step):
        evidence.apply(FrontendLifecycleChanged(FrontendState.STOPPED), VoiceCorrelation(SESSION))
        await runtime.mute()

    async def ready(step):
        result = evidence.state.update_task(VoiceTaskRecord(step.data["work_id"], "source-turn", WorkStatus.COMPLETED, 1, result=step.data["result_tag"]))
        assert result.disposition is VoiceStateDisposition.APPLIED
        request = SpeechRequest(conversation_id="conversation-1", id=step.data["work_id"], text=step.data["result_tag"],
                                kind=SpeechKind.RESULT, created_at=clock.now(), correlation_id="corr-1", source=source())
        await scheduler.handle_core_event(ProtocolEnvelope(message_type="brain.speech.requested", payload=request.to_payload()))

    async def checkpoint(step):
        reports = list((tmp_path / "benchmarks" / "voice-sessions").glob("*.json"))
        assert len(reports) == 1
        frozen = reports[0].read_bytes()
        await runtime.mute()
        assert [task.result for task in evidence.state.snapshot.tasks] == ["late-result-1", "late-result-2"]
        assert not evidence.state.active_tasks and session.spoken == [] and core.turns == []
        assert close_calls == [2000] and session.closed
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND and runtime._metrics is None
        assert reports[0].read_bytes() == frozen
        assert json.loads(frozen)["session_duration_seconds"] == 2
        assert [message.text for message in evidence.state.recent_context().messages] == ["source request"]

    await driver.run(fixture, {"provider.output_started": started, "device.output_busy": busy,
                              "control.stop": lambda step: runtime.mute(), "provider.session_closed": closed,
                              "brain.ready": ready, "control.checkpoint": checkpoint})
