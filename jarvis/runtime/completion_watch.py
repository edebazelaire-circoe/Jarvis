"""Veilleur de fin de tâche : réveiller la voix pour dire un compte rendu (IDLE et SLEEP).

Hors séance (`BACKGROUND`), personne n'écoute le flux d'évènements de Core : le
`SpeechScheduler` n'existe que pendant ACTIVE (Décision 33), et Core ne rejoue
rien (Décision 31). Un compte rendu publié pendant IDLE ou SLEEP n'aurait donc
aucune bouche. Ce veilleur garde un abonnement à `/v1/events` tant que Voice
est au repos et ne retient qu'une chose : une demande de parole qui rapporte la
fin d'une tâche entière (`is_task_completion_speech`). Il ne parle pas, il ne
rouvre pas : il remet le texte à Voice (`on_completion`), qui rouvre une séance
et le fait dire. La sous-tâche ne produit jamais de telle demande : Core ne
reçoit le relais de fin qu'une fois toutes les tâches de fond rendues
(`AgentTaskTracker.whole_task_finished`, `claude_local._push_notice`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.domain.voice_rest import is_task_completion_speech

#: Pause avant de se réabonner après une coupure du flux (Core redémarré, websocket fermé).
RECONNECT_DELAY_S = 2.0


class CompletionWatcher:
    def __init__(
        self,
        *,
        core: Any,
        on_completion: Callable[[ProtocolEnvelope], Awaitable[None]],
        journal: Any | None = None,
        reconnect_delay_s: float = RECONNECT_DELAY_S,
    ) -> None:
        self.core = core
        self.on_completion = on_completion
        self.journal = journal
        self.reconnect_delay_s = reconnect_delay_s
        self._task: asyncio.Task[None] | None = None
        self._failing = False
        #: Tant que Voice a une séance, c'est le `SpeechScheduler` qui écoute : le veilleur se tait.
        self.listening = True
        self.seen = 0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="jarvis-completion-watch")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, object] | None = None) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=data or {})

    async def handle(self, envelope: ProtocolEnvelope) -> bool:
        """Un évènement : rend True s'il a été remis à Voice comme fin de tâche."""

        if not self.listening or not is_task_completion_speech(envelope.message_type, envelope.payload):
            return False
        self.seen += 1
        await self.on_completion(envelope)
        return True

    async def _run(self) -> None:
        while True:
            stream = None
            try:
                stream = self.core.events()
                async for envelope in stream:
                    if self._failing:
                        self._failing = False
                        self._emit("voice.completion_watch.restored", "Flux d'évènements Core rétabli")
                    await self.handle(envelope)
            except asyncio.CancelledError:
                aclose = getattr(stream, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception:  # noqa: BLE001 - fermeture au mieux
                        pass
                raise
            except Exception as exc:  # noqa: BLE001 - dit une fois par épisode, puis on se réabonne
                if not self._failing:
                    self._failing = True
                    self._emit("voice.completion_watch.failed", f"Flux d'évènements Core interrompu : {type(exc).__name__}",
                               level="warning", data={"code": "completion_watch_stream_failed"})
            await asyncio.sleep(self.reconnect_delay_s)
