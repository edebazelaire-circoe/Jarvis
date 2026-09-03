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
        self._bridge_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._visual("idle")

    def _visual(self, state: str) -> None:
        if self.signals is not None:
            self.signals.state(state)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, object] | None = None) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=data)

    async def run(self) -> None:
        self._trace("voice.start", "Voice runtime started")
        try:
            async for keyword in self.wakeword.detections():
                if self._stop.is_set():
                    break
                if self.runtime.state is not VoiceLifecycleState.BACKGROUND:
                    continue
                self._trace("voice.wake", "Wake detected", data={"source": keyword})
                await self.activate()
                bridge_task = self._bridge_task
                if bridge_task is None:
                    continue
                outcome = (await asyncio.gather(bridge_task, return_exceptions=True))[0]
                if self.runtime.state is not VoiceLifecycleState.BACKGROUND:
                    await self.mute()
                if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                    self._trace("voice.failure", str(outcome), level="error")
                    raise outcome
        finally:
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
        suspend = getattr(self.wakeword, "suspend", None)
        if suspend is not None:
            await suspend()
        self.activity.reset()
        self.runtime.state = VoiceLifecycleState.ACTIVE
        if self.signals is not None:
            self.signals.alert(None)
        self._visual("listening")
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
            journal=self.journal,
        )
        self._bridge_task = asyncio.create_task(bridge.run(), name="jarvis-realtime-bridge")

    async def mute(self) -> None:
        bridge_task, self._bridge_task = self._bridge_task, None
        if bridge_task is not None and bridge_task is not asyncio.current_task():
            bridge_task.cancel()
            await asyncio.gather(bridge_task, return_exceptions=True)
        session, self._session = self._session, None
        if session is not None:
            await session.close()
        resume = getattr(self.wakeword, "resume", None)
        if resume is not None and not self._stop.is_set():
            await resume()
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
        self._trace("voice.stop", "Voice runtime stopped")
