from __future__ import annotations

import io
import asyncio
import wave

import pytest

from jarvis.core.actions import ActionBroker
from jarvis.core.orchestrator import JarvisOrchestrator
from jarvis.core.session import SessionStateMachine
from jarvis.core.tools import ToolRegistry
from jarvis.domain.events import JarvisState
from jarvis.domain.errors import ProviderError
from jarvis.domain.messages import AudioClip
from jarvis.domain.results import SpeechResult, TranscriptionResult
from jarvis.runtime.voice import VoiceRuntime

from conftest import RecordingStatePublisher, RecordingTTS, ScriptedAgent


def make_clip(ms=200):
    frames = int(16000 * ms / 1000)
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * frames)
    return AudioClip(out.getvalue())


class FakeRecorder:
    def __init__(self, clip):
        self.clip = clip
        self.started = False
        self.aborted = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False
        return self.clip

    def abort(self):
        self.aborted = True


class FakeTranscriber:
    def __init__(self, text):
        self.text = text
        self.clips = []

    async def transcribe(self, clip):
        self.clips.append(clip)
        return TranscriptionResult(self.text, 3, "fake", "fake")


class FailingTranscriber:
    async def transcribe(self, clip):
        raise ProviderError("openai", "transcription", "network down", retryable=True)


class BlockingTTS:
    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def speak(self, text, *, interrupt):
        self.started.set()
        for _ in range(500):
            if interrupt.cancelled:
                self.cancelled.set()
                return SpeechResult(1, True, "fake", "fake")
            await asyncio.sleep(0.001)
        return SpeechResult(500, False, "fake", "fake")


@pytest.mark.asyncio
async def test_fake_audio_to_transcription_to_agent_to_tts(agent_result_factory):
    agent = ScriptedAgent(agent_result_factory(text="Réponse vocale."))
    publisher = RecordingStatePublisher()
    state = SessionStateMachine(publisher)
    tts = RecordingTTS()
    orchestrator = JarvisOrchestrator(
        agent=agent,
        tts=tts,
        state=state,
        tools=ToolRegistry(),
        broker=ActionBroker({}),
    )
    await state.initialize()
    recorder = FakeRecorder(make_clip())
    transcriber = FakeTranscriber("Question vocale")
    voice = VoiceRuntime(recorder=recorder, transcriber=transcriber, orchestrator=orchestrator)
    await voice.press()
    assert state.state == JarvisState.LISTENING
    await voice.release()
    assert agent.turns[0].text == "Question vocale"
    assert tts.texts == ["Réponse vocale."]
    assert state.state == JarvisState.IDLE
    assert transcriber.clips[0].duration_ms >= 190


@pytest.mark.asyncio
async def test_transcription_provider_failure_is_spoken_visible_and_recovers(agent_result_factory):
    publisher = RecordingStatePublisher()
    state = SessionStateMachine(publisher)
    tts = RecordingTTS()
    orchestrator = JarvisOrchestrator(
        agent=ScriptedAgent(agent_result_factory(text="unused")),
        tts=tts,
        state=state,
        tools=ToolRegistry(),
        broker=ActionBroker({}),
    )
    await state.initialize()
    voice = VoiceRuntime(
        recorder=FakeRecorder(make_clip()),
        transcriber=FailingTranscriber(),
        orchestrator=orchestrator,
    )
    await voice.press()
    await voice.release()
    assert any(event.state == JarvisState.ERROR for event in publisher.events)
    assert tts.texts and "transcrire" in tts.texts[-1]
    assert state.state == JarvisState.IDLE


@pytest.mark.asyncio
async def test_voice_runtime_releases_capture_lock_so_ptt_can_barge_into_speech(agent_result_factory):
    publisher = RecordingStatePublisher()
    state = SessionStateMachine(publisher)
    tts = BlockingTTS()
    orchestrator = JarvisOrchestrator(
        agent=ScriptedAgent(agent_result_factory(text="Reponse longue.")),
        tts=tts,
        state=state,
        tools=ToolRegistry(),
        broker=ActionBroker({}),
    )
    await state.initialize()
    recorder = FakeRecorder(make_clip())
    voice = VoiceRuntime(
        recorder=recorder,
        transcriber=FakeTranscriber("Question"),
        orchestrator=orchestrator,
    )
    await voice.press()
    release_task = asyncio.create_task(voice.release())
    await asyncio.wait_for(tts.started.wait(), 1)

    await asyncio.wait_for(voice.press(), 0.25)
    await asyncio.wait_for(tts.cancelled.wait(), 1)
    await release_task

    assert recorder.started is True
    assert state.state == JarvisState.LISTENING
