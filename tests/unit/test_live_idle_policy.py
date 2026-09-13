from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from jarvis.domain.live_idle import LiveIdleEvidence
from jarvis.domain.v2 import VoiceLifecycleState
from jarvis.domain.voice_architecture import VoiceArchitectureId
from jarvis.domain.voice_frontend import VoiceStopReason
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self):
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class Wake:
    async def suspend_for_active_session(self): pass
    async def resume(self): pass
    async def close(self): pass


class Owner:
    def __init__(self) -> None:
        self.idle_calls = 0

    async def idle_candidate(self) -> None:
        self.idle_calls += 1


def runtime_with(evidence: LiveIdleEvidence, *, continuation: bool = False):
    clock = Clock()

    async def unused(_context):
        raise AssertionError

    runtime = PersistentVoiceRuntime(
        wakeword=Wake(), core=SimpleNamespace(), realtime_factory=unused,
        active_timeout_s=5, clock=clock, auto_turn=True,
        conversation_architecture=VoiceArchitectureId.DUPLEX,
    )
    runtime.runtime.state = VoiceLifecycleState.ACTIVE
    runtime._bridge = SimpleNamespace(
        live_idle_evidence=lambda: evidence, tool_in_flight=True,
    )
    runtime._speech = SimpleNamespace(immediate_continuation_pending=continuation)
    owner = Owner()
    runtime._session = SimpleNamespace(_lifecycle_owner=owner)
    reasons = []

    async def mute(reason=None):
        reasons.append(reason)

    runtime.mute = mute
    clock.advance(5)
    return runtime, clock, owner, reasons


@pytest.mark.parametrize("evidence", [
    LiveIdleEvidence(False, True, False, False),
    LiveIdleEvidence(True, False, False, False),
    LiveIdleEvidence(True, True, True, False),
    LiveIdleEvidence(True, True, False, True),
])
async def test_live_idle_fails_closed_on_unknown_or_busy_local_evidence(evidence):
    runtime, _, owner, reasons = runtime_with(evidence)
    assert await runtime.check_timeout() is False
    assert owner.idle_calls == 0
    assert reasons == []


async def test_live_idle_ignores_backend_job_but_honours_bounded_continuation():
    evidence = LiveIdleEvidence(True, True, False, False)
    held, _, owner, reasons = runtime_with(evidence, continuation=True)
    assert await held.check_timeout() is False
    assert owner.idle_calls == 0 and reasons == []

    idle, _, owner, reasons = runtime_with(evidence, continuation=False)
    assert await idle.check_timeout() is True
    assert owner.idle_calls == 1
    assert reasons == [VoiceStopReason.IDLE]


async def test_duplex_brain_progress_does_not_extend_idle_but_device_audio_does():
    runtime, clock, _, _ = runtime_with(LiveIdleEvidence(True, True, False, False))
    await runtime.brain_activity()
    assert runtime.activity.expired()
    await runtime.visual_speaking()
    assert not runtime.activity.expired()
    clock.advance(5)
    assert runtime.activity.expired()
