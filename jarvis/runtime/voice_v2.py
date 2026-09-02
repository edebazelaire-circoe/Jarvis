from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from jarvis.core.v2_services import SystemClock
from jarvis.domain.v2 import AddressingDecision, VoiceLifecycleState
from jarvis.ports.v2 import Clock, RealtimeSession, WakeWordBackend
from jarvis.protocol.client import LocalCoreClient


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

    def __init__(self, *, wakeword: WakeWordBackend, core: LocalCoreClient, realtime_factory: Callable[[dict[str, object]], Awaitable[RealtimeSession]], active_timeout_s: float = 90.0, clock: Clock | None = None) -> None:
        self.wakeword = wakeword
        self.core = core
        self.realtime_factory = realtime_factory
        self.clock = clock or SystemClock()
        self.activity = UsefulActivityTracker(timeout_s=active_timeout_s, clock=self.clock)
        self.runtime = VoiceRuntimeState()
        self._session: RealtimeSession | None = None
        self._bridge_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def run(self) -> None:
        try:
            async for _keyword in self.wakeword.detections():
                if self._stop.is_set():
                    break
                if self.runtime.state is VoiceLifecycleState.BACKGROUND:
                    await self.activate()
        finally:
            await self.close()

    async def activate(self) -> None:
        if self.runtime.state is not VoiceLifecycleState.BACKGROUND:
            return
        self.runtime.state = VoiceLifecycleState.CONNECTING
        if self.runtime.conversation_id is None:
            conversation = await self.core.create_conversation()
            self.runtime.conversation_id = str(conversation["id"])
        context = await self.core.context(self.runtime.conversation_id)
        try:
            self._session = await self.realtime_factory(context)
        except Exception:
            self.runtime.state = VoiceLifecycleState.ERROR
            await self.mute()
            raise
        suspend = getattr(self.wakeword, "suspend", None)
        if suspend is not None:
            await suspend()
        self.activity.reset()
        self.runtime.state = VoiceLifecycleState.ACTIVE
        from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
        bridge = RealtimeConversationBridge(core=self.core, session=self._session, conversation_id=self.runtime.conversation_id, audio=SoundDeviceRealtimeAudio(), on_addressed=self.addressed_activity, on_mute=self.mute)
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

    async def addressed_activity(self) -> None:
        self.activity.reset(AddressingDecision.ADDRESSED)

    async def ambient_activity(self) -> None:
        self.activity.reset(AddressingDecision.AMBIENT)

    async def check_timeout(self) -> bool:
        if self.runtime.state is VoiceLifecycleState.ACTIVE and self.activity.expired():
            await self.mute()
            return True
        return False

    async def close(self) -> None:
        self._stop.set()
        await self.mute()
        await self.wakeword.close()
        await self.core.close()
