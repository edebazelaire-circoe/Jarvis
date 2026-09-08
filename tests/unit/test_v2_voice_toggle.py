from __future__ import annotations

import asyncio
import base64
import json

import pytest

from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
from jarvis.domain.v2 import ProtocolEnvelope, VoiceLifecycleState
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio
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
        auto_turn=False,
        session=http,  # type: ignore[arg-type]
    )

    update = websocket.sent[0]
    turn_detection = update["session"]["audio"]["input"]["turn_detection"]  # type: ignore[index]
    assert turn_detection is None

    await session.send_audio(b"\x01\x00" * 2400)
    assert await session.finish_input() is True
    assert [event["type"] for event in websocket.sent[-2:]] == [
        "input_audio_buffer.commit",
        "response.create",
    ]


@pytest.mark.asyncio
async def test_realtime_session_defaults_to_server_vad_and_jarvis_persona():
    websocket = FakeWebSocket()
    session = await OpenAIRealtimeSession.connect(
        api_key="test-key",
        model="test-model",
        voice="cedar",
        context={},
        session=FakeHttpSession(websocket),  # type: ignore[arg-type]
    )
    assert session is not None

    update = websocket.sent[0]["session"]  # type: ignore[index]
    turn_detection = update["audio"]["input"]["turn_detection"]
    assert turn_detection["type"] == "server_vad"
    assert turn_detection["create_response"] is True
    assert turn_detection["interrupt_response"] is True
    assert turn_detection["silence_duration_ms"] > 0
    assert update["audio"]["output"]["voice"] == "cedar"
    assert "JARVIS" in update["instructions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_event, expected",
    [
        ("input_audio_buffer.speech_started", "realtime.speech_started"),
        ("input_audio_buffer.speech_stopped", "realtime.speech_stopped"),
        ("input_audio_buffer.committed", "realtime.input_committed"),
    ],
)
async def test_provider_maps_server_vad_turn_events(provider_event, expected):
    import aiohttp

    class Message:
        type = aiohttp.WSMsgType.TEXT

        @staticmethod
        def json():
            return {"type": provider_event, "item_id": "item-1"}

    class IterableWebSocket(FakeWebSocket):
        def __aiter__(self):
            async def stream():
                yield Message()

            return stream()

    websocket = IterableWebSocket()
    session = OpenAIRealtimeSession(websocket, FakeHttpSession(websocket), owns_http=False)  # type: ignore[arg-type]
    assert [event.message_type async for event in session.events()] == [expected]


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

    async def finish_input(self) -> bool:
        self.finish_calls += 1
        self.order.append("finish_input")
        self.finished.set()
        return True

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


class FakeAudio(SoundDeviceRealtimeAudio):
    instances: list["FakeAudio"] = []
    order: list[str] = []
    pcm = b"\x01\x00" * 2400

    def __init__(self, *, input_device=None, output_device=None) -> None:  # noqa: ANN001
        super().__init__(input_device=input_device, output_device=output_device)
        self.started = asyncio.Event()
        self.input_stopped = asyncio.Event()
        self.closed = False
        self.input_device = input_device
        self.output_device = output_device
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self._enqueue(self.pcm)
        self.started.set()

    async def stop_input(self) -> None:
        self.order.append("stop_input")
        await super().stop_input()
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
        audio_input_device=3,
        audio_output_device=7,
    )
    run_task = asyncio.create_task(runtime.run())

    await wakeword.queue.put("f9")
    while not FakeAudio.instances:
        await asyncio.sleep(0)
    await asyncio.wait_for(FakeAudio.instances[0].started.wait(), timeout=1)
    assert runtime.runtime.state is VoiceLifecycleState.ACTIVE
    assert wakeword.active_session_suspensions == 1
    assert FakeAudio.instances[0].input_device == 3
    assert FakeAudio.instances[0].output_device == 7

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


class FakeAutoTurnSession:
    """Provider driven by server VAD: it commits and answers with no submit call."""

    def __init__(self) -> None:
        self.closed = False
        self.finish_calls = 0
        self.captured = asyncio.Event()
        self.responded = asyncio.Event()

    async def send_audio(self, pcm: bytes) -> None:
        if pcm:
            self.captured.set()

    async def finish_input(self) -> bool:
        self.finish_calls += 1
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result

    async def send_context(self, text: str) -> None:
        del text

    async def events(self):
        await self.captured.wait()
        yield ProtocolEnvelope(message_type="realtime.speech_started", payload={})
        yield ProtocolEnvelope(message_type="realtime.input_committed", payload={"item_id": "item-1"})
        yield ProtocolEnvelope(message_type="realtime.audio", payload={"pcm_b64": ""})
        yield ProtocolEnvelope(message_type="realtime.audio_done", payload={})
        yield ProtocolEnvelope(message_type="realtime.response_done", payload={"status": "completed"})
        self.responded.set()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_auto_turn_answers_without_a_second_key_press(monkeypatch):
    import jarvis.runtime.realtime_audio as realtime_audio

    FakeAudio.instances.clear()
    order: list[str] = []
    FakeAudio.order = order
    monkeypatch.setattr(FakeAudio, "pcm", b"ab" * 2400)
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    wakeword = FakeWakeWord()
    session = FakeAutoTurnSession()
    signals = RecordingSignals()
    journal = RecordingJournal()

    async def factory(context):
        del context
        return session

    runtime = PersistentVoiceRuntime(
        wakeword=wakeword,
        core=FakeCore(),  # type: ignore[arg-type]
        realtime_factory=factory,  # type: ignore[arg-type]
        signals=signals,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
        auto_turn=True,
    )
    run_task = asyncio.create_task(runtime.run())
    try:
        await wakeword.queue.put("f9")
        await asyncio.wait_for(wakeword.resumed.wait(), timeout=1)

        # One press, one full turn: the provider closed it on silence.
        assert session.finish_calls == 0
        assert order == ["stop_input"]
        assert session.closed is True
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert signals.states == ["idle", "thinking", "listening", "thinking", "speaking", "idle"]
        assert not run_task.done()
        kinds = [event["kind"] for event in journal.events]
        assert "voice.input_submitted" in kinds
        assert "voice.manual_submit" not in kinds
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_auto_turn_key_press_cancels_instead_of_submitting(monkeypatch):
    import jarvis.runtime.realtime_audio as realtime_audio

    FakeAudio.instances.clear()
    FakeAudio.order = []
    monkeypatch.setattr(FakeAudio, "pcm", b"")
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    wakeword = FakeWakeWord()
    session = FakeAutoTurnSession()
    journal = RecordingJournal()

    async def factory(context):
        del context
        return session

    runtime = PersistentVoiceRuntime(
        wakeword=wakeword,
        core=FakeCore(),  # type: ignore[arg-type]
        realtime_factory=factory,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
        auto_turn=True,
    )
    run_task = asyncio.create_task(runtime.run())
    try:
        await wakeword.queue.put("f9")
        while not FakeAudio.instances:
            await asyncio.sleep(0)
        await asyncio.wait_for(FakeAudio.instances[0].started.wait(), timeout=1)

        await wakeword.queue.put("f9")
        await asyncio.wait_for(wakeword.resumed.wait(), timeout=1)

        assert session.finish_calls == 0
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert "voice.manual_cancel" in [event["kind"] for event in journal.events]
        assert not run_task.done()
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("frames, accepted", [(0, False), (1200, False), (2399, False), (2400, True), (4800, True)])
async def test_provider_only_commits_at_least_100ms_of_pcm(frames, accepted):
    websocket = FakeWebSocket()
    session = OpenAIRealtimeSession(websocket, FakeHttpSession(websocket), owns_http=False)
    pcm = b"\x01\x00" * frames
    await session.send_audio(pcm)

    assert await session.finish_input() is accepted
    types = [event["type"] for event in websocket.sent]
    assert types.count("input_audio_buffer.commit") == int(accepted)
    assert types.count("response.create") == int(accepted)
    if frames:
        assert base64.b64decode(websocket.sent[0]["audio"]) == pcm
    else:
        assert websocket.sent == []


@pytest.mark.asyncio
async def test_provider_accumulates_chunks_and_resets_after_commit():
    websocket = FakeWebSocket()
    session = OpenAIRealtimeSession(websocket, FakeHttpSession(websocket), owns_http=False)
    chunk = b"\x01\x00" * 1200
    await session.send_audio(chunk)
    assert await session.finish_input() is False
    await session.send_audio(chunk)
    assert await session.finish_input() is True
    assert await session.finish_input() is False
    await session.send_audio(chunk)
    assert await session.finish_input() is False
    assert [event["type"] for event in websocket.sent] == [
        "input_audio_buffer.append", "input_audio_buffer.append",
        "input_audio_buffer.commit", "response.create", "input_audio_buffer.append",
    ]


@pytest.mark.asyncio
async def test_failed_audio_send_cannot_make_buffer_eligible(monkeypatch):
    websocket = FakeWebSocket()
    session = OpenAIRealtimeSession(websocket, FakeHttpSession(websocket), owns_http=False)

    async def fail_send(payload):
        raise OSError("connection lost")

    monkeypatch.setattr(websocket, "send_json", fail_send)
    with pytest.raises(OSError, match="connection lost"):
        await session.send_audio(b"\x01\x00" * 2400)
    assert await session.finish_input() is False
    assert websocket.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_count", [2, 64, 65])
async def test_stop_input_drains_scheduled_callbacks_before_end_marker(chunk_count):
    websocket = FakeWebSocket()
    session = OpenAIRealtimeSession(websocket, FakeHttpSession(websocket), owns_http=False)
    audio = SoundDeviceRealtimeAudio()
    loop = asyncio.get_running_loop()
    chunk = b"\x01\x00" * 1200

    class InputStream:
        def stop(self):
            for _ in range(chunk_count):
                loop.call_soon_threadsafe(audio._enqueue, chunk)

        def close(self):
            pass

    audio._input = InputStream()
    pump = asyncio.create_task(audio.pump_input(session))
    try:
        await asyncio.wait_for(audio.stop_input(), timeout=1)
        await asyncio.wait_for(pump, timeout=1)
        assert audio.captured_bytes == chunk_count * len(chunk)
        assert audio.sent_bytes == min(chunk_count, 64) * len(chunk)
        assert audio._queue.empty()
        assert await session.finish_input() is True
        assert [event["type"] for event in websocket.sent[-2:]] == [
            "input_audio_buffer.commit", "response.create",
        ]
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)


class ProviderSessionWithResponse(OpenAIRealtimeSession):
    """Exercise real adapter sends/commit validation with deterministic responses."""

    def __init__(self):
        websocket = FakeWebSocket()
        super().__init__(websocket, FakeHttpSession(websocket), owns_http=False)
        self.finished = asyncio.Event()

    async def finish_input(self) -> bool:
        accepted = await super().finish_input()
        if accepted:
            self.finished.set()
        return accepted

    async def events(self):
        await self.finished.wait()
        yield ProtocolEnvelope(message_type="realtime.audio", payload={"pcm_b64": ""})
        yield ProtocolEnvelope(message_type="realtime.response_done", payload={"status": "completed"})


@pytest.mark.asyncio
@pytest.mark.parametrize("frames", [0, 1200])
async def test_short_turn_keeps_runtime_alive_for_next_f9(monkeypatch, tmp_path, frames):
    import jarvis.runtime.realtime_audio as realtime_audio
    from jarvis.runtime.control_center import ControlCenter
    from jarvis.runtime.journal import RuntimeJournal

    FakeAudio.instances.clear()
    monkeypatch.setattr(FakeAudio, "pcm", b"\x01\x00" * frames)
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    wakeword = FakeWakeWord()
    signals = RecordingSignals()
    sessions = []

    async def factory(context):
        session = ProviderSessionWithResponse()
        sessions.append(session)
        return session

    runtime = PersistentVoiceRuntime(
        wakeword=wakeword, core=FakeCore(), realtime_factory=factory,
        signals=signals, journal=RuntimeJournal(tmp_path), audio_input_device=3,
    )
    run_task = asyncio.create_task(runtime.run())

    async def wait_for_audio(count):
        while len(FakeAudio.instances) < count:
            await asyncio.sleep(0)
        await FakeAudio.instances[count - 1].started.wait()

    try:
        await wakeword.queue.put("f9")
        await asyncio.wait_for(wait_for_audio(1), timeout=1)
        await wakeword.queue.put("f9")
        await asyncio.wait_for(wakeword.resumed.wait(), timeout=1)
        assert not run_task.done()
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert sessions[0].ws.closed
        assert not sessions[0].finished.is_set()
        assert not any(e["type"] in {"input_audio_buffer.commit", "response.create"} for e in sessions[0].ws.sent)
        assert "trop court" in signals.alerts[-1]

        wakeword.resumed.clear()
        monkeypatch.setattr(FakeAudio, "pcm", b"\x01\x00" * 2400)
        await wakeword.queue.put("f9")
        await asyncio.wait_for(wait_for_audio(2), timeout=1)
        assert signals.alerts[-1] is None
        await wakeword.queue.put("f9")
        await asyncio.wait_for(wakeword.resumed.wait(), timeout=1)
        assert sessions[1].finished.is_set()
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert not run_task.done()

        class Request:
            query = {"limit": "100"}

        control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
        events = json.loads((await control.trace(Request())).text)
        skipped = next(e for e in events if e["kind"] == "voice.input_skipped")
        assert skipped["level"] == "warning"
        assert skipped["data"]["code"] == "audio_input_too_short"
        assert skipped["data"]["sent_duration_ms"] == frames / 24
        submitted = next(e for e in events if e["kind"] == "voice.input_submitted")
        assert submitted["data"] == {
            "conversation_id": "conversation-1", "input_device": 3,
            "captured_bytes": 4800, "sent_bytes": 4800, "sent_duration_ms": 100.0,
        }
        assert json.loads((await control.errors(Request())).text) == []
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_submission_before_audio_start_is_skipped_and_closes_session(monkeypatch):
    import jarvis.runtime.realtime_audio as realtime_audio

    FakeAudio.instances.clear()
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    session = ProviderSessionWithResponse()
    journal = RecordingJournal()

    async def factory(context):
        return session

    runtime = PersistentVoiceRuntime(
        wakeword=FakeWakeWord(), core=FakeCore(), realtime_factory=factory, journal=journal,
    )
    try:
        await runtime.activate()
        assert await runtime.submit_active_turn(source="f9") is False
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert session.ws.closed
        assert session.ws.sent == []
        skipped = next(e for e in journal.events if e["kind"] == "voice.input_skipped")
        assert skipped["data"]["code"] == "audio_input_not_ready"
        assert not any(e["level"] == "error" for e in journal.events)
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "raw, expected",
    [(None, True), ("", True), ("auto", True), ("AUTO", True), ("manual", False), (" Manual ", False)],
)
def test_turn_mode_parsing(raw, expected):
    from jarvis.v2_config import parse_turn_mode

    assert parse_turn_mode(raw) is expected


def test_turn_mode_rejects_unknown_values():
    from jarvis.domain.errors import ConfigurationError
    from jarvis.v2_config import parse_turn_mode

    with pytest.raises(ConfigurationError):
        parse_turn_mode("half")


def test_realtime_defaults_are_hands_free_and_low_timbre(monkeypatch, tmp_path):
    from jarvis.v2_config import V2Settings

    for name in ("OPENAI_REALTIME_VOICE", "JARVIS_VOICE_TURN_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))

    settings = V2Settings.load()
    assert settings.realtime_voice == "cedar"
    assert settings.auto_turn is True
