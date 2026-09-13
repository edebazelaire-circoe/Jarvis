"""Deterministic replays for the three highest-risk voice regressions.

The fixture driver only advances evidence time.  Decisions stay in the real
brain stack or speech scheduler; loop turns below are synchronization, never a
source of a replay outcome.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.domain.v2 import SpeechKind
from jarvis.runtime.voice_metrics import VoiceSessionMetricRecorder
from tests.integration.async_conversation_harness import voice_stack
from tests.replay.voice_replay import ReplayClock, ReplayDriver, load_replay_fixture
from tests.unit.test_v2_speech_scheduler import (
    FakeCore,
    FakeVoiceSession,
    brain_envelope,
    build_scheduler,
    busy_surface,
    finish_speech,
    release_surface,
    speech_envelope,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "voice_replay"
SYNC_TIMEOUT_S = 3.0

pytestmark = pytest.mark.asyncio


async def _eventually(predicate, *, message: str) -> None:  # noqa: ANN001
    """Yield until an observable production condition holds."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + SYNC_TIMEOUT_S
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError(message)
        await asyncio.sleep(0)


class _MetricJournal:
    """Journal sink that feeds the production Task18 report derivation."""

    def __init__(self, recorder: VoiceSessionMetricRecorder) -> None:
        self.events: list[dict[str, object]] = []
        self.recorder = recorder

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        event = {"kind": kind, "message": message, "level": level, "data": data or {}}
        self.events.append(event)
        self.recorder.observe(event)

    def count(self, kind: str) -> int:
        return sum(event["kind"] == kind for event in self.events)

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.events if event["kind"] == kind]


async def test_thinking_pause_wait_stays_silent_on_the_full_voice_stack(tmp_path, monkeypatch):
    fixture = load_replay_fixture(FIXTURES / "thinking_pause_wait.json")
    replay_clock = ReplayClock(fixture.origin)

    async with voice_stack(tmp_path, monkeypatch) as stack:
        await stack.wake()
        handles = []

        async def user_turn(step):  # noqa: ANN001
            assert step.data["addressing"] == "uncertain"
            handles.append(await stack.user_says(
                "il faudrait peut être réfléchir encore un instant avant de décider",
                item_id=str(step.data["turn_id"]),
            ))

        async def checkpoint(step):  # noqa: ANN001
            assert step.data["checkpoint_id"] == "policy_settled"
            handle = handles[0]
            assert handle.turn.addressing.value == "uncertain"
            handle.finish(public_summary="")
            await _eventually(
                lambda: stack.core.brain.active_turn_count == 0,
                message="WAIT turn did not settle",
            )

        await ReplayDriver(replay_clock).run(
            fixture,
            {"user.turn": user_turn, "control.checkpoint": checkpoint},
        )

        assert replay_clock.elapsed_ms == 2_900
        assert stack.session.spoken == []
        assert stack.events.of("brain.speech.requested") == []
        assert stack.events.of("brain.work.started") == []
        assert await stack.assistant_turns() == []


async def test_stale_ack_is_superseded_before_35_9s_release_and_metric_uses_replay_clock(tmp_path):
    fixture = load_replay_fixture(FIXTURES / "stale_ack_35_9s.json")
    replay_clock = ReplayClock(fixture.origin)
    recorder = VoiceSessionMetricRecorder(
        runtime_root=tmp_path,
        journal=object(),
        architecture="duplex",
        provider_id="fixture",
        model_id="scripted-surface",
        configuration_id="voice-replay",
        clock=replay_clock.monotonic,
        wall_clock=replay_clock.now,
    )
    recorder.start(conversation_id="conversation-1", session_id="test-session")
    journal = _MetricJournal(recorder)
    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session, journal=journal, clock=replay_clock)
    held_output: str | None = None
    superseded_before_release = False

    await scheduler.start()
    try:
        await _eventually(lambda: core.subscriptions == 1, message="scheduler did not subscribe")

        async def output_busy(step):  # noqa: ANN001
            nonlocal held_output
            held_output = await busy_surface(scheduler, output_id=str(step.data["output_id"]))

        async def enqueue(step):  # noqa: ANN001
            candidate = str(step.data["candidate_id"])
            if step.data["kind"] == "ack":
                envelope = speech_envelope(
                    "acknowledgement that must become stale",
                    kind=SpeechKind.ACK,
                    correlation_id="corr-1",
                    speech_id=candidate,
                    ttl_s=float(step.data["ttl_ms"]) / 1000,
                )
            else:
                envelope = speech_envelope(
                    "result for the current intent",
                    kind=SpeechKind.RESULT,
                    correlation_id="corr-2",
                    speech_id=candidate,
                )
            await core.publish(envelope)
            await _eventually(
                lambda: journal.count("voice.speech.queued") >= (1 if candidate == "old-ack" else 2),
                message=f"{candidate} was not queued",
            )

        async def new_turn(step):  # noqa: ANN001
            nonlocal superseded_before_release
            assert step.data["turn_id"] == "new-turn"
            await core.publish(brain_envelope(
                "brain.turn.accepted",
                {"turn_id": "new-turn", "revision": 2},
                correlation_id="corr-2",
            ))
            await _eventually(
                lambda: journal.count("voice.speech.superseded") == 1,
                message="old acknowledgement was not superseded",
            )
            superseded_before_release = session.spoken == [] and replay_clock.elapsed_ms == 28_000

        async def release(step):  # noqa: ANN001
            assert superseded_before_release
            assert held_output == step.data["output_id"]
            await release_surface(scheduler, held_output)
            await _eventually(lambda: len(session.spoken) == 1, message="current result was not dispatched")
            await finish_speech(scheduler, session)

        await ReplayDriver(replay_clock).run(
            fixture,
            {
                "device.output_busy": output_busy,
                "scheduler.enqueue": enqueue,
                "user.turn": new_turn,
                "device.release": release,
            },
        )
    finally:
        await scheduler.stop()

    assert [request.id for request in session.spoken] == ["new-result"]
    assert journal.of("voice.speech.superseded")[0]["data"]["speech_id"] == "old-ack"
    dispatched = journal.of("voice.speech.dispatched")
    assert dispatched[-1]["data"]["queue_wait_ms"] == 7_900.0

    report = recorder.finish(status="stopped")
    assert report["session_duration_seconds"] == 35.9
    assert report["event_counts"]["stale_cancellation"] == 1
    assert report["event_counts"]["unnecessary_acknowledgement"] == 0
    assert report["latency_metrics"]["speech_queue_wait_ms"]["max_ms"] == 7_900.0


async def test_backend_85_7s_does_not_block_later_turn_admission_on_full_stack(tmp_path, monkeypatch):
    fixture = load_replay_fixture(FIXTURES / "backend_nonblocking_85_7s.json")
    replay_clock = ReplayClock(fixture.origin)

    async with voice_stack(tmp_path, monkeypatch, active_timeout_s=120.0) as stack:
        await stack.wake()
        handles = []
        arrival_times: list[int] = []
        slow_released_when_admitted: list[bool] = []
        historical_results = []

        async def user_turn(step):  # noqa: ANN001
            handle = await stack.user_says(
                f"Jarvis request {step.data['content_tag']}",
                item_id=str(step.data["turn_id"]),
            )
            handles.append(handle)
            arrival_times.append(replay_clock.elapsed_ms)
            if len(handles) > 1:
                slow_released_when_admitted.append(handles[0].release.is_set())

        async def hold(step):  # noqa: ANN001
            await handles[0].start_work(str(step.data["work_id"]))

        async def ready(step):  # noqa: ANN001
            result = await handles[0].say(
                str(step.data["result_tag"]), kind=SpeechKind.RESULT,
                work_id=str(step.data["work_id"]),
            )
            historical_results.append(result)
            await handles[0].complete_work(str(step.data["work_id"]), summary=result.text)
            await _eventually(
                lambda: any(
                    event["data"].get("speech_id") == result.id
                    and event["data"].get("status") == "deferred"
                    and event["data"].get("reason") == "stale_source"
                    for event in stack.journal.of("voice.speech.presentation_decided")
                ),
                message="historical result was not retained as stale-source pending speech",
            )

        async def release(step):  # noqa: ANN001
            assert step.data["work_id"] == "slow-work"
            handles[0].finish(public_summary=historical_results[0].text)
            await _eventually(
                lambda: stack.core.brain.active_turn_count == 2,
                message="slow backend turn did not finish",
            )

        await ReplayDriver(replay_clock).run(
            fixture,
            {
                "user.turn": user_turn,
                "brain.hold": hold,
                "brain.ready": ready,
                "brain.release": release,
            },
        )

        assert arrival_times == [0, 33_000, 78_000]
        assert slow_released_when_admitted == [False, False]
        assert replay_clock.elapsed_ms == 85_700
        assert len(stack.backend.handles) == 3
        assert stack.journal.count("voice.brain_turn_submitted") == 3
        assert stack.core_journal.count("core.brain.backend_task_started") == 1
        assert stack.session.spoken == []
        state = stack.core.brain.working_state(stack.conversation_id)
        assert historical_results[0].text in state.known_public_facts
        for handle in handles[1:]:
            handle.finish(public_summary="")
