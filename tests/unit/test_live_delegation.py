"""Bounded Live delegation polling and exact append policy."""
import asyncio
from types import SimpleNamespace

import pytest

from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelRef
from jarvis.domain.voice_events import VoiceDelegationRequested
from jarvis.domain.voice_frontend import (
    FrontendState, ProviderDelegationId, VoiceCorrelation, VoiceFrontendConfig, VoiceOperation,
    VoiceOperationKind, VoiceOperationStatus, VoiceSessionId,
)
from jarvis.runtime.live_delegation import LiveDelegationController
from jarvis.runtime.live_frontend_session import LiveFrontendSession
from tests.fakes.voice_frontend import FakeVoiceFrontend


class Core:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.calls = []

    async def submit_back_brain_task(self, conversation_id, **kwargs):
        self.calls.append(("submit", conversation_id, kwargs))
        return SimpleNamespace(status="accepted", job_id="stable-job")

    async def back_brain_task_status(self, conversation_id, job_id):
        self.calls.append(("status", conversation_id, job_id))
        value = next(self.statuses)
        if isinstance(value, BaseException):
            raise value
        return value


class Session:
    session_id = VoiceSessionId("live-session")
    conversation_id = "conversation"

    def __init__(self, frontend, core):
        self.frontend, self.core = frontend, core
        self.flushed = False
        self._operations = 0

    def operation_id(self):
        self._operations += 1
        return f"operation-{self._operations}"

    async def flush_observations(self):
        self.flushed = True
        self.core.calls.append(("flush",))


async def ready(frontend):
    await frontend.start(VoiceFrontendConfig(DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"))),
                         operation=VoiceOperation("start", VoiceCorrelation("live-session")))


async def wait_closed(controller):
    async with asyncio.timeout(1):
        while controller._tasks:
            await asyncio.sleep(0)


async def test_progress_is_quiet_and_fresh_result_is_exact_commentary_after_core_restart():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    core = Core((ConnectionError("Core restarting"),
                 {"status": "running", "fresh": True, "progress": {"public_summary": "Exact provisional fact"}},
                 {"status": "completed", "fresh": True, "result": {"text": "Exact final result"}}))
    session = Session(frontend, core)
    controller = LiveDelegationController(session, poll_interval_s=.001)
    event = frontend.event(VoiceDelegationRequested(3), correlation=VoiceCorrelation(
        "live-session", provider_delegation_id=ProviderDelegationId("delegation")))

    assert controller.offer(event) and controller.offer(event)
    await wait_closed(controller)

    assert core.calls[0] == ("flush",) and core.calls[1][0] == "submit"
    appends = [(kind, operation.correlation.provider_delegation_id, value.text)
               for kind, operation, value in frontend.calls
               if kind in {VoiceOperationKind.QUIET_CONTEXT, VoiceOperationKind.SPOKEN_RESULT}]
    assert appends == [
        (VoiceOperationKind.QUIET_CONTEXT, "delegation", "Exact provisional fact"),
        (VoiceOperationKind.SPOKEN_RESULT, "delegation", "Exact final result"),
    ]
    assert sum(call[0] == "submit" for call in core.calls) == 1


@pytest.mark.parametrize("terminal", [
    {"status": "completed", "fresh": False, "result": {"text": "Stale result"}},
    {"status": "failed", "fresh": False, "error": "backend failed"},
])
async def test_stale_or_failed_result_is_never_injected(terminal):
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    controller = LiveDelegationController(Session(frontend, Core((terminal,))), poll_interval_s=.001)
    event = frontend.event(VoiceDelegationRequested(1), correlation=VoiceCorrelation(
        "live-session", provider_delegation_id=ProviderDelegationId("delegation")))

    assert controller.offer(event)
    await wait_closed(controller)

    assert not any(kind in {VoiceOperationKind.QUIET_CONTEXT, VoiceOperationKind.SPOKEN_RESULT}
                   for kind, _, _ in frontend.calls)


async def test_uncertain_frontend_stop_remains_unknown_for_reaping():
    frontend = FakeVoiceFrontend(close_confirmed=False)
    await ready(frontend)
    session = LiveFrontendSession(frontend, "live-session")

    await session.close()

    assert session.stop_result.status is VoiceOperationStatus.UNKNOWN
    assert session.stop_result.state is FrontendState.UNKNOWN_REAP_REQUIRED


async def test_pending_trigger_capacity_is_bounded_and_duplicate_is_idempotent():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    session = Session(frontend, Core(()))
    gate = asyncio.Event()
    async def blocked_flush():
        await gate.wait()
    session.flush_observations = blocked_flush
    controller = LiveDelegationController(session, max_pending=1)
    first = frontend.event(VoiceDelegationRequested(1), correlation=VoiceCorrelation(
        "live-session", provider_delegation_id=ProviderDelegationId("first")))
    second = frontend.event(VoiceDelegationRequested(1), correlation=VoiceCorrelation(
        "live-session", provider_delegation_id=ProviderDelegationId("second")))

    assert controller.offer(first) is True
    assert controller.offer(first) is True
    assert controller.offer(second) is False

    await controller.close()
