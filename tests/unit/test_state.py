from __future__ import annotations

import json

import pytest

from jarvis.adapters.file_state_bus import FileStatePublisher
from jarvis.core.session import SessionStateMachine
from jarvis.domain.errors import StateTransitionError
from jarvis.domain.events import JarvisState, StateEvent

from conftest import RecordingStatePublisher


@pytest.mark.asyncio
async def test_state_machine_rejects_illegal_transition():
    publisher = RecordingStatePublisher()
    state = SessionStateMachine(publisher)
    with pytest.raises(StateTransitionError):
        await state.transition(JarvisState.SPEAKING)


@pytest.mark.asyncio
async def test_visualizer_state_files_are_compatible_and_cleaned(tmp_path):
    bus = FileStatePublisher(tmp_path)
    await bus.publish(StateEvent(JarvisState.TRANSCRIBING, "t"))
    assert (tmp_path / ".voice_state").read_text() == "listening"
    await bus.publish(StateEvent(JarvisState.AWAITING_CONFIRMATION, "t", "oui/non"))
    assert (tmp_path / ".voice_state").read_text() == "thinking"
    assert (tmp_path / ".voice_alert").read_text() == "oui/non"
    await bus.publish(StateEvent(JarvisState.SPEAKING, "t"), waveform=[1, 2])
    payload = json.loads((tmp_path / ".voice_waveform").read_text())
    assert len(payload["samples"]) == 64
    await bus.cleanup()
    assert (tmp_path / ".voice_state").read_text() == "idle"
    assert not (tmp_path / ".voice_waveform").exists()
    assert not (tmp_path / ".voice_alert").exists()

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,end",
    [
        (JarvisState.IDLE, JarvisState.LISTENING),
        (JarvisState.IDLE, JarvisState.THINKING),
        (JarvisState.IDLE, JarvisState.ERROR),
        (JarvisState.LISTENING, JarvisState.TRANSCRIBING),
        (JarvisState.LISTENING, JarvisState.IDLE),
        (JarvisState.LISTENING, JarvisState.ERROR),
        (JarvisState.TRANSCRIBING, JarvisState.THINKING),
        (JarvisState.TRANSCRIBING, JarvisState.ERROR),
        (JarvisState.THINKING, JarvisState.AWAITING_CONFIRMATION),
        (JarvisState.THINKING, JarvisState.SPEAKING),
        (JarvisState.THINKING, JarvisState.IDLE),
        (JarvisState.THINKING, JarvisState.ERROR),
        (JarvisState.AWAITING_CONFIRMATION, JarvisState.LISTENING),
        (JarvisState.AWAITING_CONFIRMATION, JarvisState.THINKING),
        (JarvisState.AWAITING_CONFIRMATION, JarvisState.SPEAKING),
        (JarvisState.AWAITING_CONFIRMATION, JarvisState.IDLE),
        (JarvisState.AWAITING_CONFIRMATION, JarvisState.ERROR),
        (JarvisState.SPEAKING, JarvisState.IDLE),
        (JarvisState.SPEAKING, JarvisState.LISTENING),
        (JarvisState.SPEAKING, JarvisState.AWAITING_CONFIRMATION),
        (JarvisState.SPEAKING, JarvisState.ERROR),
        (JarvisState.ERROR, JarvisState.IDLE),
        (JarvisState.ERROR, JarvisState.LISTENING),
    ],
)
async def test_all_documented_legal_transitions(start, end):
    publisher = RecordingStatePublisher()
    state = SessionStateMachine(publisher, initial=start)
    await state.transition(end)
    assert state.state == end


@pytest.mark.asyncio
async def test_initialize_recovers_stale_visualizer_runtime_files(tmp_path):
    (tmp_path / ".voice_state").write_text("speaking")
    (tmp_path / ".voice_alert").write_text("stale")
    (tmp_path / ".voice_waveform").write_text('{"ts":0,"samples":[1]}')
    state = SessionStateMachine(FileStatePublisher(tmp_path))
    await state.initialize()
    assert (tmp_path / ".voice_state").read_text() == "idle"
    assert not (tmp_path / ".voice_alert").exists()
    assert not (tmp_path / ".voice_waveform").exists()
