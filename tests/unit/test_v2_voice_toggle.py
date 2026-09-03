from __future__ import annotations

import asyncio

import pytest

from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
from jarvis.domain.v2 import ProtocolEnvelope, VoiceLifecycleState
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.closed = False

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


class FakeHttpSession:
    def __init__(self, websocket: FakeWebSocket) -> None:
        self.websocket = websocket

    async def ws_connect(self, url: str, *, headers: dict[str, str], heartbeat: int):
        del url, headers, heartbeat
        return self.websocket


@pytest.mark.asyncio
async def test_realtime_session_uses_manual_turn_detection_and_submit_sequence():
    websocket = FakeWebSocket()
    http = FakeHttpSession(websocket)
    session = await OpenAIRealtimeSession.connect(
        api_key="test-key",
        model="test-model",
        voice="test-voice",
        context={},
        session=http,  # type: ignore[arg-type]
    )

    update = websocket.sent[0]
    turn_detection = update["session"]["audio"]["input"]["turn_detection"]  # type: ignore[index]
    assert turn_detection is None

    await session.finish_input()
    assert [event["type"] for event in websocket.sent[-2:]] == [
        "input_audio_buffer.commit",
        "response.create",
    ]


class FakeWakeWord:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.active_session_suspensions = 0
        self.resumed = asyncio.Event()
        self.closed = False

    async def detections(self):
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        return None

    async def suspend_for_active_session(self) -> None:
        self.active_session_suspensions += 1

    async def resume(self) -> None:
        self.resumed.set()

    async def close(self) -> None:
        self.closed = True


class FakeCore:
    async def create_conversation(self) -> dict[str, str]:
        return {"id": "conversation-1"}

    async def context(self, conversation_id: str) -> dict[str, object]:
        assert conversation_id == "conversation-1"
        return {}

    async def close(self) -> None:
        return None


class FakeRealtimeSession:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.finished = asyncio.Event()
        self.closed = False
        self.finish_calls = 0

    async def send_audio(self, pcm: bytes) -> None:
        del pcm

    async def finish_input(self) -> None:
        self.finish_calls += 1
        self.order.append("finish_input")
        self.finished.set()

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result

    async def send_context(self, text: str) -> None:
        del text

    async def events(self):
        await self.finished.wait()
        yield ProtocolEnvelope(message_type="realtime.audio", payload={"pcm_b64": ""})
        yield ProtocolEnvelope(message_type="realtime.audio_done", payload={})
        yield ProtocolEnvelope(message_type="realtime.response_done", payload={"status": "completed"})

    async def close(self) -> None:
        self.closed = True


class FakeAudio:
    instances: list["FakeAudio"] = []
    order: list[str] = []

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.input_stopped = asyncio.Event()
        self.closed = False
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self.started.set()

    async def pump_input(self, session: FakeRealtimeSession) -> None:
        del session
        await self.input_stopped.wait()

    async def stop_input(self) -> None:
        self.order.append("stop_input")
        self.input_stopped.set()

    async def play_b64(self, value: str) -> None:
        del value

    async def close(self) -> None:
        self.closed = True


class RecordingSignals:
    def __init__(self) -> None:
        self.states: list[str] = []
        self.alerts: list[str | None] = []
        self.heartbeats = 0
        self.is_offline = False

    def state(self, value: str) -> None:
        self.states.append(value)

    def alert(self, message: str | None) -> None:
        self.alerts.append(message)

    def heartbeat(self) -> None:
        self.heartbeats += 1

    def offline(self) -> None:
        self.is_offline = True


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})


@pytest.mark.asyncio
async def test_second_f9_submits_audio_and_returns_to_background_after_response(monkeypatch):
    import jarvis.runtime.realtime_audio as realtime_audio

    FakeAudio.instances.clear()
    order: list[str] = []
    FakeAudio.order = order
    wakeword = FakeWakeWord()
    session = FakeRealtimeSession(order)
    signals = RecordingSignals()
    journal = RecordingJournal()

    async def realtime_factory(context: dict[str, object]) -> FakeRealtimeSession:
        assert context == {}
        return session

    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    runtime = PersistentVoiceRuntime(
        wakeword=wakeword,
        core=FakeCore(),  # type: ignore[arg-type]
        realtime_factory=realtime_factory,  # type: ignore[arg-type]
        signals=signals,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
    )
    run_task = asyncio.create_task(runtime.run())

    await wakeword.queue.put("f9")
    while not FakeAudio.instances:
        await asyncio.sleep(0)
    await asyncio.wait_for(FakeAudio.instances[0].started.wait(), timeout=1)
    assert runtime.runtime.state is VoiceLifecycleState.ACTIVE
    assert wakeword.active_session_suspensions == 1

    await wakeword.queue.put("f9")
    await asyncio.wait_for(session.finished.wait(), timeout=1)
    await asyncio.wait_for(wakeword.resumed.wait(), timeout=1)

    assert session.finish_calls == 1
    assert order == ["stop_input", "finish_input"]
    assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    assert signals.states == ["idle", "thinking", "listening", "thinking", "speaking", "idle"]
    assert {event["kind"] for event in journal.events} >= {
        "voice.manual_submit",
        "voice.input_submitted",
        "voice.background",
    }

    run_task.cancel()
    await asyncio.gather(run_task, return_exceptions=True)
    assert signals.heartbeats == 1
    assert signals.is_offline is True
