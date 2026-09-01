from __future__ import annotations

import pytest

from jarvis.adapters.file_state_bus import CompositeStatePublisher
from jarvis.domain.events import JarvisState, StateEvent

from conftest import RecordingStatePublisher


class FailingPublisher:
    async def publish(self, event, *, waveform=None):
        raise ConnectionError("UI down")

    async def cleanup(self):
        raise ConnectionError("UI down")


@pytest.mark.asyncio
async def test_optional_visual_sink_failure_does_not_break_good_sink():
    good = RecordingStatePublisher()
    composite = CompositeStatePublisher(good, FailingPublisher())
    await composite.publish(StateEvent(JarvisState.THINKING, "t"))
    assert good.events[-1].state == JarvisState.THINKING
    await composite.cleanup()
    assert good.cleaned is True
