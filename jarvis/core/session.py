from __future__ import annotations

import asyncio
from collections.abc import Sequence

from jarvis.domain.errors import StateTransitionError
from jarvis.domain.events import JarvisState, StateEvent
from jarvis.ports.state import StatePublisher


_ALLOWED: dict[JarvisState, set[JarvisState]] = {
    JarvisState.IDLE: {JarvisState.LISTENING, JarvisState.THINKING, JarvisState.ERROR},
    JarvisState.LISTENING: {JarvisState.TRANSCRIBING, JarvisState.IDLE, JarvisState.ERROR},
    JarvisState.TRANSCRIBING: {JarvisState.THINKING, JarvisState.ERROR},
    JarvisState.THINKING: {
        JarvisState.AWAITING_CONFIRMATION,
        JarvisState.SPEAKING,
        JarvisState.IDLE,
        JarvisState.ERROR,
    },
    JarvisState.AWAITING_CONFIRMATION: {
        JarvisState.LISTENING,
        JarvisState.THINKING,
        JarvisState.SPEAKING,
        JarvisState.IDLE,
        JarvisState.ERROR,
    },
    JarvisState.SPEAKING: {
        JarvisState.IDLE,
        JarvisState.LISTENING,
        JarvisState.AWAITING_CONFIRMATION,
        JarvisState.ERROR,
    },
    JarvisState.ERROR: {JarvisState.IDLE, JarvisState.LISTENING},
}


class SessionStateMachine:
    def __init__(self, publisher: StatePublisher, *, initial: JarvisState = JarvisState.IDLE) -> None:
        self._publisher = publisher
        self._state = initial
        self._lock = asyncio.Lock()

    @property
    def state(self) -> JarvisState:
        return self._state

    async def initialize(self) -> None:
        await self._publisher.publish(StateEvent(self._state))

    async def transition(
        self,
        new_state: JarvisState,
        *,
        turn_id: str | None = None,
        message: str | None = None,
        waveform: Sequence[float] | None = None,
    ) -> None:
        async with self._lock:
            if new_state == self._state:
                await self._publisher.publish(StateEvent(new_state, turn_id, message), waveform=waveform)
                return
            allowed = _ALLOWED[self._state]
            if new_state not in allowed:
                raise StateTransitionError(f"Transition interdite: {self._state.value} -> {new_state.value}")
            self._state = new_state
            await self._publisher.publish(StateEvent(new_state, turn_id, message), waveform=waveform)

    async def recover_to_idle(self, *, turn_id: str | None = None, message: str | None = None) -> None:
        async with self._lock:
            if self._state != JarvisState.ERROR:
                self._state = JarvisState.ERROR
                await self._publisher.publish(StateEvent(JarvisState.ERROR, turn_id, message))
            self._state = JarvisState.IDLE
            await self._publisher.publish(StateEvent(JarvisState.IDLE, turn_id))

    async def cleanup(self) -> None:
        self._state = JarvisState.IDLE
        await self._publisher.publish(StateEvent(JarvisState.IDLE))
        await self._publisher.cleanup()
