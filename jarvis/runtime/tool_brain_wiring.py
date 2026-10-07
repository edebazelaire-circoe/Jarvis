"""Câblage du Tool Brain à Core : sources de réveil et construction (handoff jarvis-tool-brain-ui-orchestrator, S5).

Contrat : `docs/tool-brain-contracts.md` §13.4. Ce module vit dans `jarvis.runtime` (Core n'importe jamais
`jarvis.runtime`) : `jarvis/app.py` lui passe l'application Core déjà construite. Core ne reçoit qu'un crochet neutre
(`ConversationEventEmitter.add_listener`). Rien ici ne modifie Core ni le cerveau principal : les sources **observent**.

Sources de réveil (chacune s'ajoute au tick de sûreté, jamais à sa place) :

- faits de conversation (`ConversationEventEmitter`) : tour utilisateur, intention d'interface, transitions et
  interruptions de parole ;
- bus de Core : changements de Board (`board.*`) ;
- scène : `SceneService.wait_for_revision` (la scène est hors du bus à dessein), reprise espacée si elle est
  indisponible (pas de boucle serrée).

`JARVIS_TOOL_BRAIN` : `off` (défaut : rien n'est construit ni démarré) ou `shadow` (observe et enregistre).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Mapping

from jarvis.domain.conversation_events import ConversationEvent, ConversationEventType as T
from jarvis.ports.scene import SceneUnavailableError
from jarvis.runtime.tool_brain_decider import tool_brain_decider_provider
from jarvis.runtime.tool_brain_runtime import ToolBrainConfig, ToolBrainMode, ToolBrainRuntime, WakeClass

TOOL_BRAIN_MODE_ENV = "JARVIS_TOOL_BRAIN"
TOOL_BRAIN_TICK_ENV = "JARVIS_TOOL_BRAIN_TICK_S"

#: Fait de conversation -> (classe de réveil, urgent). Les faits non listés ne réveillent pas.
EVENT_WAKES: Mapping[T, tuple[WakeClass, bool | None]] = {
    T.USER_TRANSCRIPT_ACCEPTED: (WakeClass.USER_TURN, None),
    T.BRAIN_TURN_ACCEPTED: (WakeClass.USER_TURN, None),
    T.BRAIN_UI_INTENT_PUBLISHED: (WakeClass.UI_INTENT, None),
    T.MOUTH_SPEECH_STARTED: (WakeClass.SPEECH, None),
    T.MOUTH_SPEECH_COMPLETED: (WakeClass.SPEECH, None),
    T.MOUTH_SPEECH_UNCONFIRMED: (WakeClass.SPEECH, None),
    T.MOUTH_FLOOR_RELEASED: (WakeClass.SPEECH, None),
    T.MOUTH_SPEECH_INTERRUPTED: (WakeClass.SPEECH, True),
    T.MOUTH_SPEECH_SUPERSEDED: (WakeClass.SPEECH, True),
    T.MOUTH_SPEECH_EXPIRED: (WakeClass.SPEECH, True),
    T.MOUTH_FLOOR_TAKEN: (WakeClass.SPEECH, True),
}
SCENE_RETRY_S = 5.0
SCENE_WAIT_S = 25.0


def mode_from_env(environ: Mapping[str, str] | None = None) -> ToolBrainMode:
    """`off` par défaut ; une valeur inconnue est `off` (un réglage douteux ne doit pas lancer des appels payés)."""

    env = os.environ if environ is None else environ
    raw = str(env.get(TOOL_BRAIN_MODE_ENV, "") or "").strip().lower()
    return ToolBrainMode.SHADOW if raw == "shadow" else ToolBrainMode.OFF


def wake_from_event(runtime: ToolBrainRuntime, event: ConversationEvent) -> bool:
    """Réveille le runtime pour un fait de conversation s'il en est un ; rend `True` si un réveil a eu lieu."""

    rule = EVENT_WAKES.get(event.event_type)
    if rule is None:
        return False
    wake_class, urgent = rule
    return runtime.wake(wake_class, event.event_type.value, urgent=urgent, conversation_id=event.conversation_id,
                        correlation_id=event.correlation_id)


class ToolBrainWakeSources:
    """Les trois sources de réveil de Core ; `start()` / `close()` encadrent leurs tâches."""

    def __init__(self, runtime: ToolBrainRuntime, *, emitter: Any, events: Any, scene: Any) -> None:
        self._runtime = runtime
        self._emitter, self._events, self._scene = emitter, events, scene
        self._tasks: list[asyncio.Task[None]] = []
        self._queue: asyncio.Queue | None = None
        self._listening = False

    def start(self) -> None:
        if self._runtime.mode is ToolBrainMode.OFF or self._tasks:
            return
        if not self._listening:
            self._emitter.add_listener(lambda event: wake_from_event(self._runtime, event))
            self._listening = True  # le crochet de l'émetteur dure autant que Core : un seul ajout
        self._queue = self._events.subscribe(max_queue=64, lossy=True)
        self._tasks = [asyncio.create_task(self._board_loop(), name="jarvis-tool-brain-board-wake"),
                       asyncio.create_task(self._scene_loop(), name="jarvis-tool-brain-scene-wake")]

    async def close(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._queue is not None:
            self._events.unsubscribe(self._queue)
            self._queue = None

    async def _board_loop(self) -> None:
        assert self._queue is not None
        while True:
            envelope = await self._queue.get()
            if str(envelope.message_type).startswith("board."):
                self._runtime.wake(WakeClass.UI_CHANGE, str(envelope.message_type),
                                   conversation_id=getattr(envelope, "conversation_id", None))

    async def _scene_loop(self) -> None:
        seen: int | None = None
        while True:
            try:
                if seen is None:
                    seen = (await self._scene.snapshot()).revision
                    continue
                current = await self._scene.wait_for_revision(seen, timeout_s=SCENE_WAIT_S)
                if current > seen:
                    seen = current
                    self._runtime.wake(WakeClass.UI_CHANGE, "scene_revision")
            except asyncio.CancelledError:
                raise
            except SceneUnavailableError:
                seen = None
                await asyncio.sleep(SCENE_RETRY_S)  # scène non servie : espacé, jamais une boucle serrée
            except Exception as exc:  # noqa: BLE001 - capture: the safety tick still covers the scene
                self._runtime.trace("tool_brain.scene_wake_failed", "Tool Brain : veille de la scène en échec",
                                     level="warning", data={"error_class": type(exc).__name__})
                seen = None
                await asyncio.sleep(SCENE_RETRY_S)


def build_tool_brain(core: Any, *, control_settings: Callable[[], Mapping[str, object]], cwd: Any, runtime_root: Any,
                     diagnostics: Any = None, environ: Mapping[str, str] | None = None
                     ) -> tuple[ToolBrainRuntime, ToolBrainWakeSources] | None:
    """Construit le Tool Brain autour de Core, ou `None` quand `JARVIS_TOOL_BRAIN` n'est pas `shadow`.

    Les services de Core ne sont lus que par `read_ui_state` ; aucun exécuteur n'est passé (S6).
    """

    env = os.environ if environ is None else environ
    mode = mode_from_env(env)
    if mode is ToolBrainMode.OFF:
        return None
    tick = ToolBrainConfig().tick_interval_s
    try:
        tick = float(env.get(TOOL_BRAIN_TICK_ENV, "") or tick)
    except ValueError:
        pass  # argued: a bad tick falls back to the default, the mode flag is what matters
    runtime = ToolBrainRuntime(
        core.scene, core.boards,
        tool_brain_decider_provider(control_settings, cwd=cwd, runtime_root=runtime_root, environ=env),
        config=ToolBrainConfig(mode=mode, tick_interval_s=max(5.0, tick)),
        intents_source=lambda conversation_id, correlation_id: core.brain.list_ui_intents(
            conversation_id, correlation_id=correlation_id),
        diagnostics=diagnostics)
    sources = ToolBrainWakeSources(runtime, emitter=core.conversation_event_emitter, events=core.events,
                                   scene=core.scene)
    return runtime, sources


__all__ = ["EVENT_WAKES", "TOOL_BRAIN_MODE_ENV", "ToolBrainWakeSources", "build_tool_brain", "mode_from_env",
           "wake_from_event"]
