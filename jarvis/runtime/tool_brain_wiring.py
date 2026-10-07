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

`JARVIS_TOOL_BRAIN` : `off` (défaut : rien n'est construit ni démarré), `shadow` (observe et enregistre) ou
`active` (S6 : file d'actions + exécuteur ; la seule valeur qui permet au Tool Brain de modifier l'écran). Toute autre
valeur est `off`. S8 : ce même réglage décide **qui possède l'écran** (`tool_brain_ownership` : matrice §16) ; l'arbitre
de propriété et la garde des actions irréversibles sont construits ici et ne se lisent que par ce réglage.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable, Mapping

from jarvis.core.speech_authority import BOARD_SWITCHED, BOARD_VOICE_BINDING_CHANGED
from jarvis.domain.conversation_events import ConversationEvent, ConversationEventType as T
from jarvis.ports.scene import SceneUnavailableError
from jarvis.runtime.tool_brain_decider import tool_brain_decider_provider
from jarvis.runtime.tool_brain_executor import UiActionExecutor, default_adapters
from jarvis.runtime.tool_brain_guardrails import DestructiveGuard, UserTurnLedger
from jarvis.runtime.tool_brain_ownership import OwnershipArbiter
from jarvis.runtime.tool_brain_queue import ToolBrainActionQueue
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
#: Faits du bus de Core qui changent l'autorité Board/Session : la file d'actions est vidée (S6).
AUTHORITY_FACTS = frozenset({BOARD_SWITCHED, BOARD_VOICE_BINDING_CHANGED})
SCENE_RETRY_S = 5.0
SCENE_WAIT_S = 25.0


def mode_from_env(environ: Mapping[str, str] | None = None) -> ToolBrainMode:
    """`off` par défaut ; une valeur inconnue est `off` (un réglage douteux ne doit pas lancer des appels payés ni
    laisser un décideur modifier l'écran). Seul `active`, écrit tel quel, donne la main à l'exécuteur."""

    env = os.environ if environ is None else environ
    raw = str(env.get(TOOL_BRAIN_MODE_ENV, "") or "").strip().lower()
    return {"shadow": ToolBrainMode.SHADOW, "active": ToolBrainMode.ACTIVE}.get(raw, ToolBrainMode.OFF)


def wake_from_event(runtime: ToolBrainRuntime, event: ConversationEvent) -> bool:
    """Réveille le runtime pour un fait de conversation s'il en est un ; rend `True` si un réveil a eu lieu."""

    rule = EVENT_WAKES.get(event.event_type)
    if rule is None:
        return False
    wake_class, urgent = rule
    runtime.note_event(event.event_type.value)  # les actions `event` de la file attendent ce fait
    return runtime.wake(wake_class, event.event_type.value, urgent=urgent, conversation_id=event.conversation_id,
                        correlation_id=event.correlation_id)


class ToolBrainWakeSources:
    """Les trois sources de réveil de Core ; `start()` / `close()` encadrent leurs tâches."""

    def __init__(self, runtime: ToolBrainRuntime, *, emitter: Any, events: Any, scene: Any,
                 arbiter: OwnershipArbiter | None = None, user_turns: UserTurnLedger | None = None) -> None:
        self._runtime = runtime
        self.arbiter, self.user_turns = arbiter, user_turns
        self._emitter, self._events, self._scene = emitter, events, scene
        self._tasks: list[asyncio.Task[None]] = []
        self._queue: asyncio.Queue | None = None
        self._listening = False

    def start(self) -> None:
        if self._runtime.mode is ToolBrainMode.OFF or self._tasks:
            return
        if not self._listening:
            self._emitter.add_listener(self._on_event)
            self._listening = True  # le crochet de l'émetteur dure autant que Core : un seul ajout
        self._queue = self._events.subscribe(max_queue=64, lossy=True)
        if self.arbiter is not None:
            self.arbiter.start()
        self._tasks = [asyncio.create_task(self._board_loop(), name="jarvis-tool-brain-board-wake"),
                       asyncio.create_task(self._scene_loop(), name="jarvis-tool-brain-scene-wake")]

    def _on_event(self, event: ConversationEvent) -> None:
        if event.event_type is T.USER_TRANSCRIPT_ACCEPTED and self.user_turns is not None:
            self.user_turns.note(event.conversation_id, event.correlation_id)  # preuve qu'une personne a parlé (S8)
        wake_from_event(self._runtime, event)

    async def close(self) -> None:
        if self.arbiter is not None:
            await self.arbiter.close()  # publie `jarvis_direct` avant que la file ne soit vidée
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
            kind = str(envelope.message_type)
            if kind.startswith("board."):
                if kind in AUTHORITY_FACTS:
                    self._runtime.note_authority_change(kind)  # avant le réveil : plus d'action de l'ancien monde
                self._runtime.note_event(kind)
                self._runtime.wake(WakeClass.UI_CHANGE, kind, conversation_id=getattr(envelope, "conversation_id", None))

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
                    self._runtime.note_event("scene_revision")
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
    """Construit le Tool Brain autour de Core, ou `None` quand `JARVIS_TOOL_BRAIN` n'est ni `shadow` ni `active`.

    `shadow` : les services de Core ne sont lus que par `read_ui_state`, aucun exécuteur. `active` : une file et un
    exécuteur (scène : `SceneService.apply_if`, Boards : `BoardService.switch(origin="brain")`) ; la porte de
    l'exécuteur relit le mode, il ne peut pas agir autrement.
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
    queue = executor = None
    holder: list[ToolBrainRuntime] = []  # the gate reads the mode of the built runtime, not a captured constant
    arbiters: list[OwnershipArbiter] = []  # ... and the owner of the screen from the arbiter built right after
    intents = lambda conversation_id, correlation_id: core.brain.list_ui_intents(  # noqa: E731
        conversation_id, correlation_id=correlation_id)
    user_turns = UserTurnLedger()
    if mode is ToolBrainMode.ACTIVE:
        adapters = default_adapters(core.scene, core.boards)
        queue = ToolBrainActionQueue(clock=time.monotonic, supported=lambda server, tool: (server, tool) in adapters)
        executor = UiActionExecutor(
            core.scene, core.boards, queue, adapters,
            gate=lambda: bool(holder) and holder[0].mode is ToolBrainMode.ACTIVE and bool(arbiters)
            and arbiters[0].executor_allowed(),
            guard=DestructiveGuard(intents=intents, user_turns=user_turns))
    runtime = ToolBrainRuntime(
        core.scene, core.boards,
        tool_brain_decider_provider(control_settings, cwd=cwd, runtime_root=runtime_root, environ=env),
        config=ToolBrainConfig(mode=mode, tick_interval_s=max(5.0, tick)),
        intents_source=intents, queue=queue, executor=executor, owner_gate=lambda: bool(arbiters) and arbiters[0].owns(),
        diagnostics=diagnostics)
    holder.append(runtime)
    arbiter = OwnershipArbiter(runtime.status, mode.value, runtime_root, trace=runtime.trace,
                               on_change=lambda old, new: runtime.flush_actions(f"ownership_{new.ownership}"))
    arbiters.append(arbiter)
    sources = ToolBrainWakeSources(runtime, emitter=core.conversation_event_emitter, events=core.events,
                                   scene=core.scene, arbiter=arbiter, user_turns=user_turns)
    return runtime, sources


__all__ = ["EVENT_WAKES", "TOOL_BRAIN_MODE_ENV", "ToolBrainWakeSources", "build_tool_brain", "mode_from_env",
           "wake_from_event"]
