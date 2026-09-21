"""GPT-Live Duplex composition with controlled provider and restricted CLI."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field

import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.back_brain import BackBrainSubmitRequest
from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelRef
from jarvis.domain.voice_state import MAX_SPEECHES, VoiceSpeechState
from jarvis.runtime.live_frontend_session import LiveFrontendSession
from tests.unit.test_back_brain_worker import harness, until


@dataclass
class LiveWire:
    incoming: asyncio.Queue = field(default_factory=asyncio.Queue)
    sent: list[dict] = field(default_factory=list)
    closed: bool = False

    def __post_init__(self):
        self.push({"type": "session.started", "event_id": "started", "session": {
            "id": "provider-live", "model": "gpt-live-1", "status": "active"}})

    async def send_json(self, value):
        self.sent.append(value)
        kind = value["type"]
        if kind.startswith("session.") and kind.endswith(".append"):
            channel = kind.removeprefix("session.").removesuffix(".append")
            self.push({"type": f"session.{channel}.appended", "client_event_id": value["event_id"],
                       "start_ms": 1, "end_ms": 2})
        elif kind == "session.close":
            self.push({"type": "session.closed", "reason": "close_requested",
                       "session": {"id": "provider-live", "status": "active"}, "usage": {"seconds": 1}})

    async def receive_json(self):
        return await self.incoming.get()

    async def close(self):
        self.closed = True

    def push(self, value):
        self.incoming.put_nowait(value)


# Ces régressions couvrent le repli `brain_orchestration=false` : le travail
# spéculatif restreint, sans outils ni sous-agents.
SPECULATIVE = DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"), brain_orchestration=False)


class CoreClient:
    def __init__(self, core):
        self.core = core

    async def bind_voice_session(self, conversation_id, session_id):
        return await self.core.voice_ledger.bind_session(conversation_id, session_id)

    async def submit_voice_observations(self, conversation_id, session_id, events):
        return await self.core.voice_ledger.ingest(conversation_id, session_id, events)

    async def register_voice_speech(self, conversation_id, correlation, intended_text):
        return await self.core.voice_ledger.register_speech(conversation_id, correlation, intended_text)

    async def submit_back_brain_task(self, conversation_id, **values):
        return await self.core.back_brain.submit(BackBrainSubmitRequest(conversation_id, **values))

    async def back_brain_task_status(self, conversation_id, job_id):
        return await self.core.back_brain.status(conversation_id, job_id)


async def test_first_live_deltas_drive_restricted_job_without_blocking_second_turn(harness, tmp_path):
    data_root = tmp_path / "data"
    core = JarvisCoreApplication(data_root=data_root, workers={"back_brain": harness.worker("claude")})
    await core.start()
    conversation = (await core.conversations.create()).id
    wire = LiveWire()
    session = await LiveFrontendSession.connect(api_key="unused", voice="marin", context={},
                                                connector=lambda: asyncio.sleep(0, result=wire), poll_interval_s=.005,
                                                architecture_config=SPECULATIVE)
    await session.attach_core(CoreClient(core), conversation)
    delivered = asyncio.Queue()

    async def consume():
        async for event in session.events():
            delivered.put_nowait(event)

    reader = asyncio.create_task(consume())
    job_id = None
    try:
        wire.push({"type": "session.input_transcript.delta", "event_id": "input-1",
                   "delta": "Compare 2 and 3.", "start_ms": 0, "end_ms": 100})
        wire.push({"type": "session.delegation.created", "event_id": "delegate-1", "offset_ms": 100,
                   "delegation": {"id": "delegation-a", "type": "delegation", "target": "client"}})
        await until(lambda: harness.processes and harness.processes[0].input)
        snapshot = (await core.voice_ledger.snapshot(conversation))["snapshot"]
        assert snapshot["users"][0]["text"] == "Compare 2 and 3."

        # The provider reader remains live while the restricted job owns its CLI.
        # Audible : des zéros (ou des 1) sont le silence que GPT-Live diffuse en continu.
        wire.push({"type": "session.output_audio.delta", "delta": base64.b64encode(b"\0\x10" * 20).decode()})
        wire.push({"type": "session.input_transcript.delta", "event_id": "input-2",
                   "delta": "And compare 5 and 8.", "start_ms": 200, "end_ms": 300})
        await until(lambda: any(event.message_type == "realtime.transcript_delta" and
                               event.payload["text"] == "And compare 5 and 8." for event in list(delivered._queue)))
        audio = next(event for event in list(delivered._queue) if event.message_type == "realtime.audio")
        session.observe_playback(audio.payload, played_ms=1, written_ms=1)
        await session.flush_observations()
        speech = (await core.voice_ledger.snapshot(conversation))["snapshot"]["speeches"][0]
        assert speech["confirmed_text"] is None and speech["played_ms"] == 1
        harness.processes[0].result("claude", "2 is smaller than 3.")
        await until(lambda: any(message["type"] == "session.commentary.append" for message in wire.sent))
        commentary = next(message for message in wire.sent if message["type"] == "session.commentary.append")
        assert commentary["content"] == "2 is smaller than 3."
        assert commentary["delegation_id"] == "delegation-a"
        assert not any("response.create" in str(message.get("type")) for message in wire.sent)
        assert all("session.input_transcript.delta" not in str(batch) for batch in wire.sent)
        job_id = (await core.state.list_jobs())[0].id
    finally:
        await session.close()
        await asyncio.gather(reader, return_exceptions=True)
        await core.stop()
    assert wire.closed
    reopened = JarvisCoreApplication(data_root=data_root, workers={"back_brain": harness.worker("claude")})
    await reopened.start()
    try:
        restored = await reopened.back_brain.status(conversation, job_id)
        assert restored["status"] == "completed" and restored["result"]["text"] == "2 is smaller than 3."
    finally:
        await reopened.stop()


async def test_long_conversation_settles_outputs_before_the_ledger_bound(harness, tmp_path):
    """Crash du 13 septembre : la 65e réponse Live dépassait MAX_SPEECHES."""
    core = JarvisCoreApplication(data_root=tmp_path / "data", workers={"back_brain": harness.worker("claude")})
    await core.start()
    conversation = (await core.conversations.create()).id
    wire = LiveWire()
    session = await LiveFrontendSession.connect(api_key="unused", voice="marin", context={},
                                                connector=lambda: asyncio.sleep(0, result=wire), poll_interval_s=.005,
                                                architecture_config=SPECULATIVE)
    await session.attach_core(CoreClient(core), conversation)
    audio_events = []

    async def consume():
        async for event in session.events():
            if event.message_type == "realtime.audio":
                audio_events.append(event)

    reader = asyncio.create_task(consume())
    try:
        for turn in range(MAX_SPEECHES + 6):
            wire.push({"type": "session.input_transcript.delta", "event_id": f"input-{turn}",
                       "delta": f"Question {turn}.", "start_ms": turn * 100, "end_ms": turn * 100 + 10})
            wire.push({"type": "session.output_audio.delta", "event_id": f"audio-{turn}",
                       "delta": base64.b64encode(b"\0\x10" * 20).decode()})  # audible
            await until(lambda: len(audio_events) == turn + 1)
            session.observe_playback(audio_events[-1].payload, played_ms=1, written_ms=1)
            if turn % 16 == 15:
                await session.flush_observations()
        # Barge-in: the bridge reports the current output as terminal.
        session.observe_playback(audio_events[-1].payload, played_ms=2, written_ms=2, terminal=True)
        await session.flush_observations()
        speeches = (await core.voice_ledger.snapshot(conversation))["snapshot"]["speeches"]
        active = {VoiceSpeechState.QUEUED.value, VoiceSpeechState.GENERATING.value, VoiceSpeechState.PLAYING.value}
        assert 0 < len(speeches) <= MAX_SPEECHES
        assert [speech["state"] for speech in speeches if speech["state"] in active] == []
    finally:
        await session.close()
        await asyncio.gather(reader, return_exceptions=True)
        await core.stop()


async def test_completed_result_is_not_reused_after_session_replacement(harness, tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path / "data", workers={"back_brain": harness.worker("claude")})
    await core.start()
    conversation = (await core.conversations.create()).id
    wire = LiveWire()
    session = await LiveFrontendSession.connect(api_key="unused", voice="marin", context={},
                                                connector=lambda: asyncio.sleep(0, result=wire), poll_interval_s=.005,
                                                architecture_config=SPECULATIVE)
    await session.attach_core(CoreClient(core), conversation)
    async def drain():
        async for _ in session.events():
            pass
    reader = asyncio.create_task(drain())
    try:
        wire.push({"type": "session.input_transcript.delta", "event_id": "i", "delta": "Analyze this",
                   "start_ms": 0, "end_ms": 10})
        wire.push({"type": "session.delegation.created", "event_id": "d", "offset_ms": 10,
                   "delegation": {"id": "old-delegation", "type": "delegation", "target": "client"}})
        await until(lambda: harness.processes and harness.processes[0].input)
        await session.close()
        harness.processes[0].result("claude", "Late result")
        await asyncio.sleep(.05)
        assert not any(message["type"] == "session.commentary.append" for message in wire.sent)
    finally:
        await asyncio.gather(reader, return_exceptions=True)
        await core.stop()
