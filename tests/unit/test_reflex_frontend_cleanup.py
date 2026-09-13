"""Close acknowledgement owns stream termination, including deferred control errors."""
import asyncio

import pytest

from jarvis.adapters.openai_realtime import OUTPUT_ID_METADATA_KEY
from jarvis.domain.voice_events import FrontendLifecycleChanged, VoiceFrontendFailed
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceCorrelation, VoiceErrorCode, VoiceOperation, VoiceReflexRequest, VoiceStopReason,
)
from tests.unit.test_realtime_frontend_adapter import operation, started


@pytest.mark.parametrize("cancel_failure", [False, True])
async def test_eof_before_close_ack_does_not_finish_consumer_before_terminal(cancel_failure):
    frontend, wire = await started()
    entered, release = asyncio.Event(), asyncio.Event()
    async def close():
        wire.close_count += 1
        wire.inbound.put_nowait(None)
        entered.set()
        await release.wait()
        wire.closed = True
    wire.close = close
    async def collect():
        return [event async for event in frontend.events()]
    consumer = asyncio.create_task(collect())
    owner = None
    try:
        if cancel_failure:
            op = VoiceOperation("reflex", VoiceCorrelation("session", output_id="reserved"))
            await frontend.request_reflex(VoiceReflexRequest("Compare les prix"), operation=op)
            wire.push(type="response.created", response={"id": "response", "metadata": {OUTPUT_ID_METADATA_KEY: "reserved"}})
            async with asyncio.timeout(1):
                while frontend._session.response_for_output("reserved") is None:
                    await asyncio.sleep(0)
            wire.fail_send = True
            await frontend.invalidate_unstarted_output(operation=op)
        else:
            owner = asyncio.create_task(frontend.stop(VoiceStopReason.USER, operation=operation()))
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.sleep(.01)
        assert not consumer.done() and not wire.closed
        release.set()
        events = await asyncio.wait_for(consumer, 1)
        terminal = [event.payload.state for event in events if isinstance(event.payload, FrontendLifecycleChanged)]
        assert terminal[-1] is (FrontendState.UNKNOWN_REAP_REQUIRED if cancel_failure else FrontendState.STOPPED)
        assert wire.closed and wire.close_count == 1
        failures = [event.payload.error for event in events if isinstance(event.payload, VoiceFrontendFailed)]
        assert [error.code for error in failures] == ([VoiceErrorCode.TRANSPORT] if cancel_failure else [])
    finally:
        release.set()
        if owner is not None:
            await owner
        await asyncio.gather(consumer, return_exceptions=True)
        await frontend.stop(VoiceStopReason.USER, operation=operation())
