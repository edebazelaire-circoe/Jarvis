"""Independent controlled Task12D regressions; no provider or device calls."""
import asyncio
import base64
from types import SimpleNamespace

import pytest

from jarvis.domain.voice_events import VoiceDelegationRequested
from jarvis.domain.voice_frontend import VoiceCorrelation, VoiceOperationKind, VoiceOperationStatus
from jarvis.runtime.live_delegation import LiveDelegationController
from jarvis.runtime.live_frontend_session import LiveFrontendSession
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from tests.integration.test_live_duplex_session import LiveWire
from tests.fakes.voice_frontend import FakeVoiceFrontend
from tests.unit.test_live_delegation import Core, Session, ready, wait_closed


def trigger(frontend, identity="delegation"):
    return frontend.event(VoiceDelegationRequested(1), correlation=VoiceCorrelation(
        "live-session", provider_delegation_id=identity))


async def test_local_correction_during_status_request_prevents_stale_result_append():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    core = Core(())
    session = Session(frontend, core)
    session.input_observation_revision = 1
    calls = 0

    async def status(*_):
        nonlocal calls
        calls += 1
        if calls == 1:
            # Local transcript is newer than the server snapshot in flight.
            session.input_observation_revision += 1
            return {"status": "completed", "fresh": True, "result": {"text": "obsolete answer"}}
        return {"status": "completed", "fresh": False, "result": {"text": "obsolete answer"}}

    core.back_brain_task_status = status
    controller = LiveDelegationController(session, poll_interval_s=.001)
    assert controller.offer(trigger(frontend))
    await wait_closed(controller)
    assert not any(kind is VoiceOperationKind.SPOKEN_RESULT for kind, _, _ in frontend.calls)
    assert calls == 2


async def test_stale_progress_is_not_injected_as_quiet_context():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    core = Core(({"status": "running", "fresh": False, "progress": {"public_summary": "obsolete fact"}},
                 {"status": "completed", "fresh": False, "result": {"text": "obsolete answer"}}))
    controller = LiveDelegationController(Session(frontend, core), poll_interval_s=.001)
    assert controller.offer(trigger(frontend))
    await wait_closed(controller)
    assert not any(kind is VoiceOperationKind.QUIET_CONTEXT for kind, _, _ in frontend.calls)


@pytest.mark.parametrize("answer", ["x" * 501, "exact answer"])
async def test_rejected_or_unconfirmed_append_never_logs_presented_or_retries(answer):
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    attempts = []

    async def unknown(update, *, operation):
        attempts.append(update.text)
        return SimpleNamespace(status=None)

    frontend.append_spoken_result = unknown
    core = Core(({"status": "completed", "fresh": True, "result": {"text": answer}},))
    session = Session(frontend, core)
    statuses = []
    session.journal = SimpleNamespace(emit=lambda *_, data, **__: statuses.append(data["status"]))
    controller = LiveDelegationController(session, poll_interval_s=.001)
    event = trigger(frontend)
    assert controller.offer(event)
    await wait_closed(controller)
    assert controller.offer(event)
    assert "presented" not in statuses
    assert len(attempts) == (0 if len(answer) > 500 else 1)


async def test_retention_saturation_does_not_rearm_old_delegation():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    core = Core(({"status": "completed", "fresh": False},) * 140)
    controller = LiveDelegationController(Session(frontend, core), poll_interval_s=.001)
    for index in range(129):
        controller.offer(trigger(frontend, f"delegation-{index}"))
        await wait_closed(controller)
    submitted = sum(call[0] == "submit" for call in core.calls)
    assert controller.offer(trigger(frontend, "delegation-0"))
    await wait_closed(controller)
    assert sum(call[0] == "submit" for call in core.calls) == submitted
    assert len(controller._seen) <= 128


async def test_canonical_flush_blocks_submission_but_not_reader_or_microphone():
    gate, blocked = asyncio.Event(), asyncio.Event()
    batches, submissions = [], []

    class HeldCore:
        async def bind_voice_session(self, *_):
            return {"result": {"disposition": "applied"}}

        async def submit_voice_observations(self, _conversation, _session, events):
            blocked.set()
            await gate.wait()
            batches.extend(events)
            return {"results": [{"disposition": "applied"} for _ in events]}

        async def submit_back_brain_task(self, *args, **kwargs):
            submissions.append((args, kwargs))
            return SimpleNamespace(status="unavailable", job_id=None)

    wire = LiveWire()
    session = await LiveFrontendSession.connect(api_key="unused", voice="marin", context={},
        connector=lambda: asyncio.sleep(0, result=wire))
    await session.attach_core(HeldCore(), "conversation")
    observed = []

    async def consume():
        async for event in session.events():
            observed.append(event)

    reader = asyncio.create_task(consume())
    try:
        wire.push({"type": "session.input_transcript.delta", "delta": "untrusted provisional",
                   "start_ms": 0, "end_ms": 10})
        wire.push({"type": "session.delegation.created", "offset_ms": 10,
                   "delegation": {"id": "d", "type": "delegation", "target": "client"}})
        await asyncio.wait_for(blocked.wait(), 1)
        wire.push({"type": "session.output_audio.delta", "delta": base64.b64encode(b"\1\0" * 20).decode()})
        async with asyncio.timeout(1):
            while not any(event.message_type == "realtime.audio" for event in observed):
                await asyncio.sleep(0)
        await asyncio.wait_for(session.send_audio(b"\0\0" * 20), 1)
        assert not submissions
        assert any(event["type"] == "session.input_audio.append" for event in wire.sent)
        gate.set()
        async with asyncio.timeout(1):
            while not submissions:
                await asyncio.sleep(0)
        assert session.input_observation_revision == 1
        assert "untrusted provisional" in str(batches)
        assert not any("pcm" in str(event).lower() for event in batches)
        assert not any(event["type"].startswith(("response.", "conversation.", "input_audio_buffer.")) for event in wire.sent)
    finally:
        gate.set()
        await asyncio.wait_for(session.close(), 3)
        await asyncio.wait_for(reader, 1)


async def test_controller_journal_failure_does_not_change_result_injection():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    core = Core(({"status": "completed", "fresh": True, "result": {"text": "exact answer"}},))
    session = Session(frontend, core)

    def broken(*_, **__):
        raise OSError("journal unavailable")

    session.journal = SimpleNamespace(emit=broken)
    controller = LiveDelegationController(session, poll_interval_s=.001)
    assert controller.offer(trigger(frontend))
    await wait_closed(controller)
    assert [value.text for kind, _, value in frontend.calls if kind is VoiceOperationKind.SPOKEN_RESULT] == ["exact answer"]


async def test_ack_journal_contains_identity_but_no_result_text_or_heard_claim(tmp_path):
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    async def acknowledged(update, *, operation):
        return SimpleNamespace(status=VoiceOperationStatus.COMPLETED)
    frontend.append_spoken_result = acknowledged
    core = Core(({"status": "completed", "fresh": True, "result": {"text": "private exact answer"}},))
    session = Session(frontend, core)
    session.journal = RuntimeJournal(tmp_path)
    controller = LiveDelegationController(session, poll_interval_s=.001)
    assert controller.offer(trigger(frontend))
    await wait_closed(controller)
    rows = read_jsonl_tail(session.journal.trace_path)
    assert [row["data"]["status"] for row in rows] == ["accepted", "append_acknowledged"]
    assert all(row["data"]["job_id"] == "stable-job" for row in rows)
    assert "private exact answer" not in str(rows)
    assert not any(word in str(rows) for word in ("heard", "presented"))
