from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from jarvis.core.v2_services import SystemClock
from jarvis.domain.v2 import AddressingDecision, VoiceLifecycleState
from jarvis.ports.v2 import Clock, RealtimeSession, WakeWordBackend
from jarvis.protocol.client import LocalCoreClient
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.visual_signals import VisualSignalBus


class UsefulActivityTracker:
    def __init__(self, *, timeout_s: float, clock: Clock | None = None) -> None:
        self.timeout_s = timeout_s
        self.clock = clock or SystemClock()
        self._last_useful = self.clock.now()

    def reset(self, decision: AddressingDecision = AddressingDecision.ADDRESSED) -> None:
        if decision is AddressingDecision.ADDRESSED:
            self._last_useful = self.clock.now()

    def expired(self) -> bool:
        return (self.clock.now() - self._last_useful).total_seconds() >= self.timeout_s


@dataclass(slots=True)
class VoiceRuntimeState:
    state: VoiceLifecycleState = VoiceLifecycleState.BACKGROUND
    conversation_id: str | None = None


class PersistentVoiceRuntime:
    """Wake/background lifecycle. Core is never stopped by mute or inactivity."""

    def __init__(
        self,
        *,
        wakeword: WakeWordBackend,
        core: LocalCoreClient,
        realtime_factory: Callable[[dict[str, object]], Awaitable[RealtimeSession]],
        active_timeout_s: float = 90.0,
        clock: Clock | None = None,
        signals: VisualSignalBus | None = None,
        journal: RuntimeJournal | None = None,
    ) -> None:
        self.wakeword = wakeword
        self.core = core
        self.realtime_factory = realtime_factory
        self.clock = clock or SystemClock()
        self.activity = UsefulActivityTracker(timeout_s=active_timeout_s, clock=self.clock)
        self.runtime = VoiceRuntimeState()
        self.signals = signals
        self.journal = journal
        self._session: RealtimeSession | None = None
        self._bridge = None
        self._bridge_task: asyncio.Task[None] | None = None
        self._turn_submitted = False
        self._stop = asyncio.Event()
        self._visual("idle")

    def _visual(self, state: str) -> None:
        if self.signals is not None:
            self.signals.state(state)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, object] | None = None) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=data)

    async def run(self) -> None:
        if self.signals is not None:
            self.signals.heartbeat()
        self._trace("voice.start", "Voice runtime started")
        detections = self.wakeword.detections()
        detection_task: asyncio.Task[str] | None = None
        try:
            while not self._stop.is_set():
                if detection_task is None:
                    detection_task = asyncio.create_task(anext(detections), name="jarvis-manual-toggle")

                if self.runtime.state is VoiceLifecycleState.BACKGROUND:
                    try:
                        keyword = await detection_task
                    except StopAsyncIteration:
                        break
                    detection_task = None
                    self._trace("voice.wake", "Wake detected", data={"source": keyword})
                    await self.activate()
                    continue

                bridge_task = self._bridge_task
                if bridge_task is None:
                    await self.mute()
                    continue

                done, _ = await asyncio.wait({detection_task, bridge_task}, return_when=asyncio.FIRST_COMPLETED)
                if detection_task in done:
                    try:
                        keyword = detection_task.result()
                    except StopAsyncIteration:
                        break
                    detection_task = None
                    if self.runtime.state is VoiceLifecycleState.ACTIVE:
                        if self._turn_submitted:
                            self._trace("voice.manual_cancel", "Manual key cancelled the active response")
                            await self.mute()
                        else:
                            await self.submit_active_turn(source=keyword)
                    continue

                outcome = (await asyncio.gather(bridge_task, return_exceptions=True))[0]
                if self.runtime.state is not VoiceLifecycleState.BACKGROUND:
                    await self.mute()
                if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                    self._trace("voice.failure", str(outcome), level="error")
                    raise outcome
        finally:
            if detection_task is not None:
                detection_task.cancel()
                await asyncio.gather(detection_task, return_exceptions=True)
            await self.close()

    async def activate(self) -> None:
        if self.runtime.state is not VoiceLifecycleState.BACKGROUND:
            return
        self.runtime.state = VoiceLifecycleState.CONNECTING
        self._visual("thinking")
        self._trace("voice.connecting", "Opening Realtime session")
        if self.runtime.conversation_id is None:
            conversation = await self.core.create_conversation()
            self.runtime.conversation_id = str(conversation["id"])
        context = await self.core.context(self.runtime.conversation_id)
        try:
            self._session = await self.realtime_factory(context)
        except Exception as exc:
            self.runtime.state = VoiceLifecycleState.ERROR
            if self.signals is not None:
                self.signals.alert(str(exc))
            self._trace("voice.provider_error", str(exc), level="error")
            await self.mute()
            raise
        await self.wakeword.suspend_for_active_session()
        self.activity.reset()
        self._turn_submitted = False
        self.runtime.state = VoiceLifecycleState.ACTIVE
        if self.signals is not None:
            self.signals.alert(None)
        self._trace("voice.active", "Realtime session active", data={"conversation_id": self.runtime.conversation_id})
        from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
        bridge = RealtimeConversationBridge(
            core=self.core,
            session=self._session,
            conversation_id=self.runtime.conversation_id,
            audio=SoundDeviceRealtimeAudio(),
            on_addressed=self.addressed_activity,
            on_mute=self.mute,
            on_listening=self.visual_listening,
            on_thinking=self.visual_thinking,
            on_speaking=self.visual_speaking,
            on_response_done=self.mute,
            journal=self.journal,
        )
        self._bridge = bridge
        self._bridge_task = asyncio.create_task(bridge.run(), name="jarvis-realtime-bridge")

    async def submit_active_turn(self, *, source: str) -> bool:
        bridge = self._bridge
        if self.runtime.state is not VoiceLifecycleState.ACTIVE or bridge is None:
            return False
        self._turn_submitted = True
        self._trace("voice.manual_submit", "Manual key submitted the active turn", data={"source": source})
        try:
            return await bridge.submit_input()
        except Exception as exc:
            self.runtime.state = VoiceLifecycleState.ERROR
            if self.signals is not None:
                self.signals.alert(f"Impossible d'envoyer la commande: {exc}")
            self._trace(
                "voice.input_submit_failed",
                str(exc),
                level="error",
                data={"source": source, "code": "voice_input_submit_failed"},
            )
            await self.mute()
            raise

    async def mute(self) -> None:
        self._bridge = None
        bridge_task, self._bridge_task = self._bridge_task, None
        if bridge_task is not None and bridge_task is not asyncio.current_task():
            bridge_task.cancel()
            await asyncio.gather(bridge_task, return_exceptions=True)
        session, self._session = self._session, None
        if session is not None:
            await session.close()
        if not self._stop.is_set():
            await self.wakeword.resume()
        self._turn_submitted = False
        self.runtime.state = VoiceLifecycleState.BACKGROUND
        self._visual("idle")
        self._trace("voice.background", "Voice returned to background")

    async def addressed_activity(self) -> None:
        self.activity.reset(AddressingDecision.ADDRESSED)

    async def ambient_activity(self) -> None:
        self.activity.reset(AddressingDecision.AMBIENT)

    async def visual_listening(self) -> None:
        if self.runtime.state is VoiceLifecycleState.ACTIVE:
            self._visual("listening")

    async def visual_thinking(self) -> None:
        if self.runtime.state is VoiceLifecycleState.ACTIVE:
            self._visual("thinking")

    async def visual_speaking(self) -> None:
        if self.runtime.state is VoiceLifecycleState.ACTIVE:
            self._visual("speaking")

    async def check_timeout(self) -> bool:
        if self.runtime.state is VoiceLifecycleState.ACTIVE and self.activity.expired():
            self._trace("voice.timeout", "Useful activity timeout reached")
            await self.mute()
            return True
        return False

    async def close(self) -> None:
        self._stop.set()
        await self.mute()
        await self.wakeword.close()
        await self.core.close()
        if self.signals is not None:
            self.signals.offline()
        self._trace("voice.stop", "Voice runtime stopped")
