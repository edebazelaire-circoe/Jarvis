from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable

from jarvis.domain.v2 import AddressingDecision
from jarvis.ports.v2 import RealtimeSession
from jarvis.protocol.client import LocalCoreClient


class ConservativeAddressingClassifier:
    FOLLOWUPS = ("oui", "non", "yes", "no", "ok", "d'accord", "et ", "mais ", "alors ", "continue", "pourquoi", "comment", "quand", "où", "qui", "quoi")

    def classify(self, text: str, *, active: bool) -> AddressingDecision:
        normalized = " ".join(text.casefold().strip().split())
        if not normalized:
            return AddressingDecision.AMBIENT
        if normalized.startswith("jarvis"):
            return AddressingDecision.ADDRESSED
        if not active:
            return AddressingDecision.AMBIENT
        if normalized.endswith("?") or normalized.startswith(self.FOLLOWUPS) or len(normalized.split()) <= 8:
            return AddressingDecision.ADDRESSED
        return AddressingDecision.UNCERTAIN


class SoundDeviceRealtimeAudio:
    """24 kHz mono PCM bridge. Raw audio is memory-only and never persisted."""

    def __init__(self, *, input_device: str | None = None, output_device: str | None = None, sample_rate: int = 24000) -> None:
        self.input_device = input_device
        self.output_device = output_device
        self.sample_rate = sample_rate
        self._input = None
        self._output = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Realtime audio requires sounddevice") from exc
        self._loop = asyncio.get_running_loop()

        def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            del frames, time_info, status
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._enqueue, bytes(indata))

        self._input = sd.RawInputStream(samplerate=self.sample_rate, channels=1, dtype="int16", device=self.input_device, blocksize=1200, callback=callback)
        self._output = sd.RawOutputStream(samplerate=self.sample_rate, channels=1, dtype="int16", device=self.output_device)
        self._input.start(); self._output.start()

    def _enqueue(self, raw: bytes) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(raw)

    async def pump_input(self, session: RealtimeSession) -> None:
        while True:
            await session.send_audio(await self._queue.get())

    async def play_b64(self, value: str) -> None:
        if self._output is not None and value:
            await asyncio.to_thread(self._output.write, base64.b64decode(value))

    async def close(self) -> None:
        for stream in (self._input, self._output):
            if stream is not None:
                try:
                    stream.abort(); stream.close()
                except Exception:
                    pass
        self._input = self._output = None


class RealtimeConversationBridge:
    def __init__(self, *, core: LocalCoreClient, session: RealtimeSession, conversation_id: str, audio: SoundDeviceRealtimeAudio, on_addressed: Callable[[], object], on_mute: Callable[[], object], classifier: ConservativeAddressingClassifier | None = None) -> None:
        self.core = core
        self.session = session
        self.conversation_id = conversation_id
        self.audio = audio
        self.on_addressed = on_addressed
        self.on_mute = on_mute
        self.classifier = classifier or ConservativeAddressingClassifier()
        self._pending_action_id: str | None = None

    async def run(self) -> None:
        await self.audio.start()
        input_task = asyncio.create_task(self.audio.pump_input(self.session), name="jarvis-realtime-mic")
        try:
            async for event in self.session.events():
                if event.message_type == "realtime.audio":
                    await self.audio.play_b64(str(event.payload.get("pcm_b64") or ""))
                elif event.message_type == "realtime.transcript":
                    text = str(event.payload.get("text") or "").strip()
                    decision = self.classifier.classify(text, active=True)
                    if decision is not AddressingDecision.ADDRESSED:
                        continue
                    normalized = " ".join(text.casefold().replace(",", " ").split())
                    if normalized == "jarvis mute":
                        maybe = self.on_mute()
                        if hasattr(maybe, "__await__"):
                            await maybe
                        break
                    await self.core.append_turn(self.conversation_id, kind="user", content=text)
                    if self._pending_action_id is not None and normalized in {"oui", "non", "yes", "no"}:
                        result = await self.core.confirm_action(self._pending_action_id, text)
                        if result.get("disposition") != "confirm":
                            self._pending_action_id = None
                        await self.session.send_context("Jarvis Core confirmation result: " + str(result))
                    maybe = self.on_addressed()
                    if hasattr(maybe, "__await__"):
                        await maybe
                elif event.message_type == "realtime.assistant_transcript":
                    text = str(event.payload.get("text") or "").strip()
                    if text:
                        await self.core.append_turn(self.conversation_id, kind="assistant", content=text)
                        maybe = self.on_addressed()
                        if hasattr(maybe, "__await__"):
                            await maybe
                elif event.message_type == "realtime.tool_call":
                    call_id = str(event.payload.get("call_id") or "")
                    name = str(event.payload.get("name") or "")
                    arguments = event.payload.get("arguments") if isinstance(event.payload.get("arguments"), dict) else {}
                    result = await self.core.call_tool(name, arguments, conversation_id=self.conversation_id)
                    action_id = result.get("action_id")
                    self._pending_action_id = str(action_id) if result.get("disposition") == "confirm" and action_id else None
                    await self.session.send_tool_result(call_id, result)
                elif event.message_type == "realtime.error":
                    raise RuntimeError("Realtime provider reported an error")
        finally:
            input_task.cancel()
            await asyncio.gather(input_task, return_exceptions=True)
            await self.audio.close()
