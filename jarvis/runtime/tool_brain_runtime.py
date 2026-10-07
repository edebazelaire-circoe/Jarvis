"""Runtime du Tool Brain : réveils, décision bornée, modes observation et actif (handoff jarvis-tool-brain-ui-orchestrator, S5-S6).

Contrat : `docs/tool-brain-contracts.md` §13. Le runtime est **un cycle de décision**, pas une source de vérité :

- **réveils** (`wake`) : un fait important (tour utilisateur, intention d'interface, transition de parole,
  changement de scène/Board) réveille tout de suite ; un **tick de sûreté** périodique rattrape un réveil raté
  mais n'est jamais le seul chemin, et ne coûte un appel de modèle que si l'état perçu a changé ;
- **coalescence** : les réveils arrivés pendant l'attente ne font qu'**une** décision (fenêtre de calme pour les
  réveils ordinaires, aucune pour les urgents), et deux décisions sont espacées d'au moins `min_interval_s` ;
- **décision** : perception (S3) + manifeste (S2) + intentions (S4) -> `ToolBrainDecider.decide` ; au plus
  `max_inspection_rounds` tours de lecture ciblée (`INSPECTION_READS`, ids contraints) avant de conclure ;
- **validation** : chaque action proposée passe `validate_call` contre l'état **frais** (référence observée = celle
  de la perception). Une action refusée est gardée avec ses refus, jamais exécutée ;
- **mode `shadow`** : le runtime ne possède **aucun exécuteur** (aucun service d'écriture ne lui est passé) : il
  enregistre ce qu'il ferait (`would_apply`) ;
- **mode `active`** (S6, `JARVIS_TOOL_BRAIN=active` seulement) : les actions `would_apply` entrent dans la file
  (`tool_brain_queue`) et l'exécuteur (`tool_brain_executor`) les exécute **quand elles sont dues**, après
  revalidation sur l'état frais ; une invalidation réveille ce runtime aussitôt pour replanifier ;
- **annulation** : un réveil urgent pendant un appel au décideur l'annule ; une décision dépassée ne rend aucune
  action (`superseded`) et la suivante part aussitôt ;
- **panne** : décideur absent, lent ou en erreur -> `backoff` explicite (suites de délais croissants), jamais de
  boucle serrée ; l'interface reste inchangée (rien n'est exécuté de toute façon).

Historique **borné** en mémoire (`decisions`, `get_decision`) pour S10 (rollout). S9 : quand un `ToolBrainEvents` est
fourni (`events=`), chaque réveil suivi d'un cycle, état capturé, lecture ciblée, décision, replanification et chaque
transition de la file devient un évènement de conversation (`tool_brain_events`, §17) ; les traces de diagnostic restent
et portent l'id de l'évènement (`conversation_event_id`) pour la jointure du détail.
"""

from __future__ import annotations

import asyncio
import enum
import itertools
import time
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Awaitable, Callable, Mapping, Sequence

from jarvis.core.conversation_event_emitter import journal_ref
from jarvis.domain.ui_intent import UiIntentDraft
from jarvis.domain.v2 import utc_now
from jarvis.ports.tool_brain import (
    DECIDER_FAILED, DECIDER_TIMEOUT, DECIDER_UNAVAILABLE, MAX_INSPECTIONS_PER_REPLY, DeciderError, InspectionRequest,
    ProposedAction,
    ToolBrainDecider, ToolBrainReply, ToolBrainRequest,
)
from jarvis.ports.v2 import DiagnosticSink
from jarvis.runtime.tool_brain_choices import UiState, build_manifest, read_ui_state, validate_call
from jarvis.runtime.tool_brain_events import JOURNALED_STATUSES, ToolBrainEvents
from jarvis.runtime.tool_brain_intents import check_intent_refs
from jarvis.runtime.tool_brain_queue import (
    AUTHORITY_CHANGED, INVALID_TRIGGER, INVALIDATED, AddResult, FAILED as ACTION_FAILED, DONE as ACTION_DONE, SCHEDULED as ACTION_SCHEDULED,
    ActionRecord, QueueError, ToolBrainActionQueue, Trigger, TriggerContext, plan_action,
)
from jarvis.runtime.tool_brain_perception import (
    INSPECTION_READS, QueueSection, SpeechSection, build_perception, get_available_actions, get_information_on,
    get_queue_state, list_related,
)

DECISION_SCHEMA = "tool_brain.decision/1"


class ToolBrainMode(str, enum.Enum):
    """`off` : rien ne tourne. `shadow` : décide et enregistre, n'exécute rien. `active` : file + exécuteur (S6)."""

    OFF = "off"
    SHADOW = "shadow"
    ACTIVE = "active"


class WakeClass(str, enum.Enum):
    USER_TURN = "user_turn"
    UI_INTENT = "ui_intent"
    SPEECH = "speech"
    UI_CHANGE = "ui_change"
    TICK = "tick"
    #: S6 : issue d'une action exécutée (invalidation -> urgent, replanifier ; échec -> ordinaire).
    ACTION = "action_result"


#: Classes qui passent la fenêtre de calme (réponse immédiate) ; `SPEECH` l'est seulement pour une interruption.
URGENT_BY_DEFAULT = frozenset({WakeClass.USER_TURN, WakeClass.UI_INTENT})

# Issues d'un pas (`step`).
IDLE, OFF, COALESCING, RATE_LIMITED, BACKOFF, UNCHANGED, DECIDED = (
    "idle", "off", "coalescing", "rate_limited", "backoff", "unchanged", "decided")

# Issues d'une décision.
COMPLETED, SUPERSEDED, FAILED, UNAVAILABLE = "completed", "superseded", "failed", "unavailable"
WOULD_APPLY, REJECTED = "would_apply", "rejected"


@dataclass(frozen=True)
class ToolBrainConfig:
    mode: ToolBrainMode = ToolBrainMode.SHADOW
    #: Filet de sûreté : réveil `TICK` quand rien n'est arrivé depuis ce délai.
    tick_interval_s: float = 30.0
    #: Calme exigé après le dernier réveil ordinaire, au plus `max_delay_s` après le premier.
    coalesce_s: float = 0.3
    max_delay_s: float = 2.0
    #: Écart minimal entre la fin d'une décision et le début de la suivante (urgent compris).
    min_interval_s: float = 1.0
    decision_timeout_s: float = 30.0
    max_inspection_rounds: int = 3
    history_size: int = 64
    #: Reprise après échec/timeout du décideur, puis décideur absent (la plus longue : une config manquante ne
    #: se corrige pas en secondes).
    failure_backoff_s: tuple[float, ...] = (5.0, 30.0, 120.0, 600.0)
    unavailable_backoff_s: tuple[float, ...] = (60.0, 300.0, 900.0)


@dataclass(frozen=True)
class ActionVerdict:
    action: ProposedAction
    verdict: str
    refusals: tuple[Mapping[str, Any], ...] = ()
    revision_drift: int | None = None
    #: S6, mode `active` : issue de l'admission en file (`outcome`, `action_id`, `code`), sinon `None`.
    queued: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        wire = {"server": self.action.server, "tool": self.action.tool, "arguments": dict(self.action.arguments),
                "reason": self.action.reason, "intent_id": self.action.intent_id, "verdict": self.verdict,
                "refusals": [dict(item) for item in self.refusals], "revision_drift": self.revision_drift}
        if self.queued is not None:
            wire["queue"] = dict(self.queued)
        return wire


@dataclass(frozen=True)
class ToolBrainDecision:
    """Une décision enregistrée (lecture seule). `to_dict()` est le format de S9/S10 : ids, comptes, verdicts."""

    decision_id: str
    seq: int
    mode: str
    outcome: str
    at: datetime
    trigger: Mapping[str, Any]
    decider: str
    model: str = ""
    perception_digest: str | None = None
    perception_bytes: int = 0
    manifest_tools: int = 0
    rounds: int = 0
    inspections: tuple[Mapping[str, Any], ...] = ()
    actions: tuple[ActionVerdict, ...] = ()
    rationale: str = ""
    latency_ms: int = 0
    cost_usd: float | None = None
    error_code: str | None = None
    error_detail: str | None = None
    #: Mouvement du backoff déclenché par cet échec (secondes), sinon `None`.
    backoff_s: float | None = None
    #: S6, mode `active` : issue de chaque opération de file demandée (`op`, `action_id`, `result`).
    queue_ops: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"schema": DECISION_SCHEMA, "decision_id": self.decision_id, "seq": self.seq, "mode": self.mode,
                "outcome": self.outcome, "at": self.at.isoformat(), "trigger": dict(self.trigger),
                "decider": self.decider, "model": self.model, "perception_digest": self.perception_digest,
                "perception_bytes": self.perception_bytes, "manifest_tools": self.manifest_tools,
                "rounds": self.rounds, "inspections": [dict(item) for item in self.inspections],
                "actions": [item.to_dict() for item in self.actions], "rationale": self.rationale,
                "latency_ms": self.latency_ms, "cost_usd": self.cost_usd, "error_code": self.error_code,
                "error_detail": self.error_detail, "backoff_s": self.backoff_s,
                **({"queue_ops": [dict(item) for item in self.queue_ops]} if self.queue_ops else {})}


@dataclass
class _Pending:
    classes: dict[WakeClass, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    first_at: float = 0.0
    last_at: float = 0.0
    urgent: bool = False
    wakes: int = 0
    conversation_id: str | None = None
    correlation_id: str | None = None
    #: Heure murale du premier réveil du lot (S9 : date de l'évènement `wake.requested`).
    first_wall: datetime | None = None
    #: Actions invalidées par l'exécuteur (S6) : `{action_id, tool, code}`, bornées ; le décideur les voit.
    invalidated: list[dict[str, Any]] = field(default_factory=list)

    def trigger(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"classes": {key.value: count for key, count in sorted(self.classes.items(),
                                                                                    key=lambda item: item[0].value)},
                                "wakes": self.wakes, "urgent": self.urgent, "reasons": list(self.reasons)}
        if self.conversation_id:
            wire["conversation_id"] = self.conversation_id
        if self.correlation_id:
            wire["correlation_id"] = self.correlation_id
        if self.invalidated:
            wire["invalidated"] = [dict(item) for item in self.invalidated]
        return wire


MAX_REASONS = 8
#: Au plus ce nombre d'invalidations de suite déclenchent un replan urgent (puis il est supprimé et dit) : un décideur
#: qui repropose sans cesse une action périmée ne fait pas tourner la boucle.
MAX_REPLAN_STREAK = 3
MAX_EXECUTIONS_PER_PUMP = 8
MAX_INVALIDATIONS_IN_TRIGGER = 4
PUMP_POLL_S = 1.0
PUMP_IDLE_S = 30.0


class ToolBrainRuntime:
    """Voir l'en-tête du module. `step()` fait un pas (testable, horloge injectée) ; `start()`/`close()` la boucle."""

    def __init__(
        self,
        scene: Any,
        boards: Any,
        decider: Callable[[], ToolBrainDecider | None],
        *,
        config: ToolBrainConfig | None = None,
        catalog: Callable[[], Awaitable[Mapping[str, Any]]] | None = None,
        speech_source: Callable[[], SpeechSection | None] | None = None,
        queue_source: Callable[[], QueueSection | None] | None = None,
        intents_source: Callable[[str, str | None], Sequence[Mapping[str, Any]]] | None = None,
        queue: ToolBrainActionQueue | None = None,
        executor: Any | None = None,
        owner_gate: Callable[[], bool] | None = None,
        diagnostics: DiagnosticSink | None = None,
        events: ToolBrainEvents | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._config = config or ToolBrainConfig()
        if not isinstance(self._config.mode, ToolBrainMode):
            raise ValueError("unknown Tool Brain mode")
        # La porte de mode : seul `active` possède une file et un exécuteur, et il exige les deux.
        if (self._config.mode is ToolBrainMode.ACTIVE) != (executor is not None and queue is not None) \
                or ((executor is None) != (queue is None)):
            raise ValueError("a queue and an executor exist exactly in active mode")
        if self._config.max_inspection_rounds < 0 or not self._config.failure_backoff_s \
                or not self._config.unavailable_backoff_s or self._config.history_size < 1:
            raise ValueError("invalid Tool Brain configuration")
        # Lecture seule : `scene` et `boards` ne servent qu'à `read_ui_state` (aucune écriture n'est jamais appelée).
        self._scene, self._boards = scene, boards
        self._decider = decider
        self._catalog = catalog
        self._speech, self._queue, self._intents = speech_source, queue_source, intents_source
        self._action_queue, self._executor = queue, executor
        #: S8 : vrai quand le Tool Brain possède l'écran (arbitre de propriété). Sinon rien n'entre en file : Jarvis agit
        #: et une action planifiée en double serait une seconde exécution. `None` : toujours (tests, avant S8).
        self._owner_gate = owner_gate
        self._last_outcome: str | None = None
        if queue is not None and queue_source is None:
            self._queue = queue.section
        if executor is not None:
            executor.attach(context=self.trigger_context, on_result=self._on_action_result, trace=self._action_trace)
        self._pump_event = asyncio.Event()
        self._pump_task: asyncio.Task[None] | None = None
        self._replan_streak = 0
        self._diagnostics = diagnostics
        #: S9 : évènements de conversation (`None` = aucun ; les ids de décision gardent alors leur forme courte).
        self._events = events
        self._cycle: dict[str, Any] | None = None
        if events is not None and queue is not None:
            queue.observe(events.queue_change)
        self._clock, self._wall = clock, wall_clock
        self._pending: _Pending | None = None
        self._event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._inflight: asyncio.Task[Any] | None = None
        self._superseded = False
        self._busy = False
        self._history: deque[ToolBrainDecision] = deque(maxlen=self._config.history_size)
        self._seq = itertools.count(1)
        self._failures = 0
        self._backoff_until = 0.0
        self._last_finished: float | None = None
        self._last_digest: str | None = None
        self._said_once: set[str] = set()
        self._latencies: deque[int] = deque(maxlen=64)
        self._counters: dict[str, int] = {"wakes": 0, "wakes_coalesced": 0, "decisions": 0, "superseded": 0,
                                          "failed": 0, "unavailable": 0, "ticks_unchanged": 0,
                                          "rate_limited": 0, "backoffs": 0, "actions_would_apply": 0,
                                          "actions_rejected": 0, "actions_queued": 0, "queue_ops": 0,
                                          "replans": 0, "replans_suppressed": 0, "authority_changes": 0,
                                          "actions_executed": 0, "completed": 0, "guard_refused": 0}
        self._wake_counts: dict[str, int] = {}

    # ------------------------------------------------------------ cycle de vie

    @property
    def mode(self) -> ToolBrainMode:
        return self._config.mode

    def start(self) -> None:
        if self._config.mode is ToolBrainMode.OFF:
            self.trace("tool_brain.off", "Tool Brain coupé (JARVIS_TOOL_BRAIN=off)", once="off")
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="jarvis-tool-brain")
            if self._executor is not None:
                self._pump_task = asyncio.create_task(self._pump_loop(), name="jarvis-tool-brain-actions")
            self.trace("tool_brain.started", "Tool Brain démarré en mode "
                       + ("actif : il exécute" if self._executor is not None else "observation"),
                       data={"mode": self._config.mode.value, "tick_interval_s": self._config.tick_interval_s})

    async def close(self) -> None:
        tasks = [task for task in (self._task, self._pump_task) if task is not None and not task.done()]
        self._task = self._pump_task = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._action_queue is not None:
            self._action_queue.invalidate_all("shutdown")  # la file est éphémère : rien ne survit à l'arrêt

    # ------------------------------------------------------------ réveils

    def wake(self, wake_class: WakeClass, reason: str = "", *, urgent: bool | None = None,
             conversation_id: str | None = None, correlation_id: str | None = None,
             invalidated: Mapping[str, Any] | None = None) -> bool:
        """Un fait important vient d'arriver. Non bloquant, jamais d'exception ; rend `False` si le runtime est coupé.

        `urgent` : passe la fenêtre de calme et annule l'appel en cours (défaut : `URGENT_BY_DEFAULT` ; une
        interruption de parole l'est explicitement).
        """

        if self._config.mode is ToolBrainMode.OFF:
            return False
        now = self._clock()
        important = wake_class in URGENT_BY_DEFAULT if urgent is None else urgent
        pending = self._pending
        if pending is None:
            pending = self._pending = _Pending(first_at=now)
        else:
            self._counters["wakes_coalesced"] += 1
        pending.classes[wake_class] = pending.classes.get(wake_class, 0) + 1
        pending.wakes += 1
        pending.last_at = now
        pending.urgent = pending.urgent or important
        if reason and len(pending.reasons) < MAX_REASONS and reason[:80] not in pending.reasons:
            pending.reasons.append(reason[:80])
        pending.conversation_id = conversation_id or pending.conversation_id
        pending.correlation_id = correlation_id or pending.correlation_id
        if pending.first_wall is None:
            pending.first_wall = self._wall()
        if self._events is not None:
            self._events.note_conversation(conversation_id)
        if invalidated is not None and len(pending.invalidated) < MAX_INVALIDATIONS_IN_TRIGGER:
            pending.invalidated.append(dict(invalidated))
        self._counters["wakes"] += 1
        self._wake_counts[wake_class.value] = self._wake_counts.get(wake_class.value, 0) + 1
        if important and self._inflight is not None and not self._inflight.done():
            self._superseded = True  # annule l'appel au décideur : sa réponse serait périmée
            self._inflight.cancel()
        elif important and self._busy:
            self._superseded = True
        self._event.set()
        self._pump_event.set()  # une parole qui avance ou s'interrompt peut rendre une action due... ou morte
        return True

    # ------------------------------------------------------------ file d'actions (S6)

    def note_event(self, name: str) -> None:
        """Un fait nommé est arrivé : les actions `event` qui l'attendent deviennent dues (une fois chacune)."""

        if self._action_queue is not None:
            self._action_queue.note_event(name)
            self._pump_event.set()

    def flush_actions(self, reason: str) -> int:
        """Vide la file d'actions (S8 : changement de propriétaire de l'écran) ; rend le nombre d'actions retirées."""

        return self._action_queue.invalidate_all(reason) if self._action_queue is not None else 0

    def note_authority_change(self, reason: str = "board_authority_changed") -> int:
        """L'autorité Board/Session a changé : toute action en attente visait un monde disparu, elle est annulée."""

        if self._action_queue is None:
            return 0
        cancelled = self._action_queue.invalidate_all(AUTHORITY_CHANGED)
        self._counters["authority_changes"] += 1
        if cancelled:
            self.trace("tool_brain.queue.authority_changed", "Tool Brain : file vidée (autorité Board/Session changée)",
                       level="warning", data={"reason": reason[:60], "cancelled": cancelled})
        return cancelled

    def trigger_context(self) -> TriggerContext:
        section = self._speech() if self._speech else None
        speech = section.data if section is not None and section.status == "wired" else None
        cache: dict[tuple[str | None, str | None], Sequence[Mapping[str, Any]]] = {}

        def intent_row(record: ActionRecord) -> Mapping[str, Any] | None:
            if self._intents is None or not record.conversation_id:
                return None
            key = (record.conversation_id, record.correlation_id)
            if key not in cache:
                try:
                    cache[key] = list(self._intents(record.conversation_id, record.correlation_id))
                except Exception as exc:  # noqa: BLE001 - capture: unreadable intents keep the action waiting
                    self.trace("tool_brain.intents_unreadable", "Intentions illisibles : l'action attend", level="warning",
                               data={"error_class": type(exc).__name__})
                    cache[key] = []
            return next((row for row in cache[key] if row.get("intent_id") == record.intent_id), None)

        return TriggerContext(self._clock(), speech, intent_row)

    async def pump(self) -> int:
        """Retire les actions mortes, exécute les dues (ordre `(priorité, séquence)`) ; rend le nombre d'issues.

        Public et sans attente propre : la boucle d'actions l'appelle, les tests la pilotent à la main.
        """

        if self._executor is None or self._action_queue is None:
            return 0
        queue, context = self._action_queue, self.trigger_context()
        for view in queue.sweep(context):
            self._action_trace(f"tool_brain.action.{view.status}", f"Tool Brain : action {view.status}", data={
                "action_id": view.record.action_id, "tool": view.record.tool, "code": view.code,
                "decision_id": view.record.decision_id, "trigger": view.record.trigger.kind})
        done = 0
        for action_id in queue.ready(context)[:MAX_EXECUTIONS_PER_PUMP]:
            result = await self._executor.execute(action_id)
            if result.terminal:
                done += 1
        return done

    async def _pump_loop(self) -> None:
        while True:
            self._pump_event.clear()
            try:
                await self.pump()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - capture: logged with its cause, the action loop must stay alive
                self.trace("tool_brain.pump_failed", "Tool Brain : pas d'exécution en échec", level="error",
                           data={"error_class": type(exc).__name__, "detail": str(exc)[:200]})
            queue = self._action_queue
            assert queue is not None
            deadline = queue.next_deadline()
            wait = PUMP_IDLE_S if deadline is None else max(0.05, min(PUMP_POLL_S, deadline - self._clock()))
            try:
                await asyncio.wait_for(self._pump_event.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass

    def _on_action_result(self, result: Any, record: ActionRecord | None) -> None:
        """Issue d'une action : une invalidation réveille le décideur avec l'état frais (borné, sans boucle serrée)."""

        if result.status in (ACTION_DONE, ACTION_SCHEDULED):
            self._counters["actions_executed"] += 1
            self._replan_streak = 0
            return
        if result.status == INVALIDATED and result.detail.get("guard"):
            # S8 : refus de garde-fou, final. Un replan reproposerait la même action destructive : pas de réveil.
            self._counters["guard_refused"] += 1
            self.trace("tool_brain.guard.refused", "Tool Brain : action gardée refusée", level="warning",
                       data={"action_id": result.action_id, "tool": record.tool if record else None, "code": result.code,
                             "codes": [item.get("code") for item in result.detail.get("refusals", ())][:6]})
            return
        if result.status == INVALIDATED:
            if self._replan_streak >= MAX_REPLAN_STREAK:
                self._counters["replans_suppressed"] += 1
                self._note_replan(result, record, suppressed=True)
                self.trace("tool_brain.replan_suppressed", "Tool Brain : replan supprimé (invalidations répétées)",
                           level="warning", data={"action_id": result.action_id, "code": result.code,
                                                  "streak": self._replan_streak})
                return
            self._replan_streak += 1
            self._counters["replans"] += 1
            self._note_replan(result, record, suppressed=False)
            self.wake(WakeClass.ACTION, "action_invalidated", urgent=True,
                      conversation_id=record.conversation_id if record else None,
                      correlation_id=record.correlation_id if record else None,
                      invalidated={"action_id": result.action_id, "tool": record.tool if record else None,
                                   "code": result.code})
        elif result.status == ACTION_FAILED:
            self.wake(WakeClass.ACTION, "action_failed", urgent=False)

    def _note_replan(self, result: Any, record: ActionRecord | None, *, suppressed: bool) -> None:
        """S9 : l'invalidation d'une action demande (ou se voit refuser) une replanification ; liée à la clôture."""

        if self._events is None:
            return
        self._events.replan(
            result.action_id, reason="action_invalidated", code=result.code, suppressed=suppressed,
            conversation_id=record.conversation_id if record else None,
            correlation_id=record.correlation_id if record else None,
            parent=self._events.action_event_id("invalidated", record) if record else None)

    def _action_trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None,
                      once: str | None = None) -> None:
        """Trace d'une action : comme `trace`, plus `conversation_event_id` de l'évènement qui la clôt (S9)."""

        payload = dict(data or {})
        status = kind.rsplit(".", 1)[-1]
        if self._events is not None and self._action_queue is not None and status in JOURNALED_STATUSES:
            view = self._action_queue.get(str(payload.get("action_id")))
            event_id = self._events.action_event_id(status, view.record) if view is not None else None
            payload.update(journal_ref(event_id))
        self.trace(kind, message, level=level, data=payload, once=once)

    # ------------------------------------------------------------ lectures (S9, S10)

    def decisions(self, limit: int = 20) -> tuple[ToolBrainDecision, ...]:
        """Les dernières décisions, de la plus ancienne à la plus récente (bornées par `history_size`)."""

        items = tuple(self._history)
        return items[-max(0, limit):] if limit else ()

    def get_decision(self, decision_id: str) -> ToolBrainDecision | None:
        return next((item for item in self._history if item.decision_id == decision_id), None)

    def status(self) -> dict[str, Any]:
        latencies = list(self._latencies)
        now = self._clock()
        return {"mode": self._config.mode.value, "running": self._task is not None and not self._task.done(),
                "pending": self._pending.trigger() if self._pending else None,
                "consecutive_failures": self._failures, "last_outcome": self._last_outcome,
                "backoff_remaining_s": round(max(0.0, self._backoff_until - now), 3),
                "counters": dict(self._counters), "wakes_by_class": dict(self._wake_counts),
                "latency_ms": {"last": latencies[-1] if latencies else None, "max": max(latencies, default=None),
                               "mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
                               "samples": len(latencies)},
                "history": len(self._history),
                **({"queue": self._action_queue.stats()} if self._action_queue is not None else {})}

    # ------------------------------------------------------------ boucle

    async def _loop(self) -> None:
        while True:
            self._event.clear()
            try:
                result = await self.step()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - capture: logged with its cause, the loop must stay alive
                self.trace("tool_brain.step_failed", "Tool Brain : pas en échec", level="error",
                            data={"error_class": type(exc).__name__, "detail": str(exc)[:200]})
                result = BACKOFF
                self._backoff_until = max(self._backoff_until, self._clock() + self._config.failure_backoff_s[0])
            timeout = self._wait_for(result)
            try:
                await asyncio.wait_for(self._event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                if self._pending is None:
                    self.wake(WakeClass.TICK, "safety_tick")  # filet de sûreté : jamais l'unique chemin

    def _wait_for(self, result: str) -> float:
        """Prochaine échéance utile ; un réveil l'interrompt toujours (l'attente n'est jamais la seule porte)."""

        now, config = self._clock(), self._config
        if result == BACKOFF:
            return max(0.01, self._backoff_until - now)
        if result == RATE_LIMITED and self._last_finished is not None:
            return max(0.01, self._last_finished + config.min_interval_s - now)
        if result == COALESCING and self._pending is not None:
            return max(0.01, min(self._pending.last_at + config.coalesce_s,
                                 self._pending.first_at + config.max_delay_s) - now)
        return config.tick_interval_s

    # ------------------------------------------------------------ un pas

    async def step(self) -> str:
        """Un pas : décide s'il y a un réveil prêt. Rend `idle`, `off`, `coalescing`, `rate_limited`, `backoff`,
        `unchanged` (tick sans changement d'état) ou `decided`."""

        config, now = self._config, self._clock()
        if config.mode is ToolBrainMode.OFF:
            return OFF
        pending = self._pending
        if pending is None:
            return IDLE
        if now < self._backoff_until:
            return BACKOFF
        if self._last_finished is not None and now < self._last_finished + config.min_interval_s:
            self._counters["rate_limited"] += 1
            return RATE_LIMITED
        if not pending.urgent and now < pending.last_at + config.coalesce_s \
                and now < pending.first_at + config.max_delay_s:
            return COALESCING
        self._pending = None
        self._superseded = False
        self._busy = True
        try:
            return await self._decide(pending)
        finally:
            self._busy = False

    # ------------------------------------------------------------ une décision

    async def _decide(self, pending: _Pending) -> str:
        started = self._clock()
        decision_id = f"tbd-{self._events.run_id + '-' if self._events else ''}{next(self._seq):06d}"
        trigger = pending.trigger()
        self._cycle = {"decision_id": decision_id, "pending": pending}
        try:
            return await self._decide_cycle(pending, decision_id, trigger, started)
        finally:
            self._cycle = None

    async def _decide_cycle(self, pending: _Pending, decision_id: str, trigger: Mapping[str, Any],
                            started: float) -> str:
        decider = self._decider()
        if self._events is not None and set(pending.classes) != {WakeClass.TICK}:
            self._note_wake(pending)
        if decider is None:
            return self._failure(decision_id, trigger, started, "", UNAVAILABLE, DECIDER_UNAVAILABLE,
                                 "no decider model is configured for the Tool Brain", pending)
        try:
            state = await read_ui_state(self._scene, self._boards)
            catalog = await self._catalog_now()
            perception = build_perception(state, speech=self._speech() if self._speech else None,
                                          queue=self._queue() if self._queue else None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: the owner failed; said, backoff, no guessed state
            return self._failure(decision_id, trigger, started, decider.name, FAILED, "tool_brain_state_unreadable",
                                 f"{type(exc).__name__}: {exc}", pending)
        digest = perception.digest()
        if set(pending.classes) == {WakeClass.TICK} and digest == self._last_digest:
            self._counters["ticks_unchanged"] += 1  # rien n'a bougé depuis la dernière décision : pas d'appel payé
            return UNCHANGED
        if self._events is not None and set(pending.classes) == {WakeClass.TICK}:
            self._note_wake(pending)  # un tick sans changement ne laisse aucun évènement : seul un cycle payé en laisse
        if self._events is not None and self._cycle is not None:
            self._cycle["snapshot"] = self._events.snapshot(
                decision_id, revision=state.ref().revision, conversation_id=pending.conversation_id,
                correlation_id=pending.correlation_id, parent=self._cycle.get("wake"))
        manifest = build_manifest(catalog, state)
        intents = self._intents_for(pending, state)
        inspections: list[dict[str, Any]] = []
        results: list[Mapping[str, Any]] = []
        reply: ToolBrainReply | None = None
        rounds = 0
        try:
            while True:
                left = max(0, self._config.max_inspection_rounds - rounds)
                request = ToolBrainRequest(decision_id, trigger, perception.data, manifest, tuple(intents),
                                           tuple(results), rounds, left)
                reply = await self._ask(decider, request)
                if self._superseded:
                    return self._superseded_decision(decision_id, trigger, started, decider, digest, perception,
                                                     manifest, rounds, inspections)
                if not reply.inspections:
                    break
                if left == 0:  # budget épuisé : le décideur devait conclure, ses lectures sont refusées et dites
                    first = len(inspections) + 1
                    inspections.extend({"read": item.read[:60], "id": (item.id or "")[:80] or None, "ok": False,
                                        "code": "budget_exhausted"} for item in reply.inspections)
                    for index, entry in enumerate(inspections[first - 1:], first):
                        self._note_inspection(entry, index)
                    break
                rounds += 1
                for wanted in reply.inspections[:MAX_INSPECTIONS_PER_REPLY]:
                    result = self._read(wanted, state, catalog)
                    results.append(result)
                    inspections.append({"read": wanted.read[:60], "id": (wanted.id or "")[:80] or None,
                                        "ok": bool(result.get("ok")), "code": result.get("code")})
                    self._note_inspection(inspections[-1], len(inspections))
        except _Superseded:
            return self._superseded_decision(decision_id, trigger, started, decider, digest, perception, manifest,
                                             rounds, inspections)
        except DeciderError as exc:
            kind = UNAVAILABLE if exc.code == DECIDER_UNAVAILABLE else FAILED
            return self._failure(decision_id, trigger, started, decider.name, kind, exc.code, exc.detail, pending,
                                 digest=digest, perception_bytes=perception.size_bytes)
        assert reply is not None
        # Validation contre l'état **frais** : la décision a pris du temps, le monde a pu bouger.
        try:
            fresh = await read_ui_state(self._scene, self._boards)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: no fresh state, no verdict: failure, never a guess
            return self._failure(decision_id, trigger, started, decider.name, FAILED, "tool_brain_state_unreadable",
                                 f"{type(exc).__name__}: {exc}", pending)
        if self._superseded:
            return self._superseded_decision(decision_id, trigger, started, decider, digest, perception, manifest,
                                             rounds, inspections)
        verdicts = tuple(self._verdict(action, fresh, state) for action in reply.actions)
        op_results: tuple[Mapping[str, Any], ...] = ()
        # S9 : la décision précède ses actions dans le journal (leur `parent_event_id`) ; elle est donc écrite avant l'admission.
        self._note_decision(decision_id, COMPLETED, reply.model, self._elapsed_ms(started), len(verdicts),
                            sum(1 for item in verdicts if item.verdict == REJECTED), None)
        if self._executor is not None and (self._owner_gate is None or self._owner_gate()):
            op_results, verdicts = self._enqueue(reply, verdicts, decision_id, perception.digest(), state.ref(),
                                                 pending)
        self._failures, self._backoff_until = 0, 0.0
        self._last_digest = digest
        self._counters["actions_would_apply"] += sum(1 for item in verdicts if item.verdict == WOULD_APPLY)
        self._counters["actions_rejected"] += sum(1 for item in verdicts if item.verdict == REJECTED)
        return self._record(ToolBrainDecision(
            decision_id, 0, self._config.mode.value, COMPLETED, self._wall(), trigger, decider.name,
            model=reply.model, perception_digest=digest, perception_bytes=perception.size_bytes,
            manifest_tools=len(manifest["tools"]), rounds=rounds, inspections=tuple(inspections), actions=verdicts,
            rationale=reply.rationale, latency_ms=self._elapsed_ms(started), cost_usd=reply.cost_usd,
            queue_ops=op_results))

    def _enqueue(self, reply: ToolBrainReply, verdicts: tuple[ActionVerdict, ...], decision_id: str, digest: str,
                 ref: Any, pending: _Pending) -> tuple[tuple[Mapping[str, Any], ...], tuple[ActionVerdict, ...]]:
        """Mode actif : opérations de file demandées, puis admission des actions `would_apply`. Rien ne s'exécute ici.

        Un refus d'admission est typé et gardé dans la décision (`queue.code`) ; une action `rejected` n'entre jamais.
        """

        queue = self._action_queue
        assert queue is not None
        ops: list[dict[str, Any]] = []
        for op in reply.queue_ops:
            self._counters["queue_ops"] += 1
            try:
                if op.op == "cancel":
                    result = queue.cancel(op.action_id)
                elif op.op == "reprioritize":
                    result = queue.reprioritize(op.action_id, op.priority or "")
                else:
                    if op.trigger is None:  # a reschedule without a trigger is not "now": it is refused
                        raise QueueError(INVALID_TRIGGER, "reschedule needs a trigger")
                    result = queue.reschedule(op.action_id, Trigger.from_payload(op.trigger))
            except QueueError as exc:
                result = exc.code
            ops.append({"op": op.op, "action_id": op.action_id, "result": result})
        out: list[ActionVerdict] = []
        for index, verdict in enumerate(verdicts):
            if verdict.verdict != WOULD_APPLY:
                out.append(verdict)
                continue
            action_id = f"act-{decision_id}-{index + 1}"
            # S9 : la conversation est figée dans l'action à son admission (ses évènements de cycle de vie doivent
            # tous aller dans la même, même si une autre conversation commence avant sa fin).
            conversation = pending.conversation_id or (self._events.conversation_id if self._events else None)
            try:
                record = plan_action(verdict.action, action_id=action_id, ref=ref, digest=digest,
                                     decision_id=decision_id, conversation_id=conversation,
                                     correlation_id=pending.correlation_id)
                old, *others = record.supersedes or (None,)
                added = queue.replace(old, record) if old else queue.add(record)
                if added.queued:
                    for extra in others:
                        queue.cancel(extra, "replaced")
            except QueueError as exc:
                added = AddResult("rejected", action_id, exc.code, exc.detail[:200])
            if added.queued:
                self._counters["actions_queued"] += 1
            out.append(replace(verdict, queued={"outcome": added.outcome, "action_id": added.action_id,
                                                "code": added.code}))
        if not any(item.queued and item.queued.get("outcome") == "queued" for item in out):
            self._replan_streak = 0  # rien n'est en vol : la prochaine invalidation peut de nouveau replanifier
        self._pump_event.set()
        return tuple(ops), tuple(out)

    async def _catalog_now(self) -> Mapping[str, Any]:
        if self._catalog is not None:
            return await self._catalog()
        from jarvis.runtime.mcp_catalog import cached_catalog

        return await cached_catalog()

    async def _ask(self, decider: ToolBrainDecider, request: ToolBrainRequest) -> ToolBrainReply:
        """Un appel au décideur, borné par `decision_timeout_s`, annulable par un réveil urgent."""

        task = asyncio.ensure_future(decider.decide(request, timeout_s=self._config.decision_timeout_s))
        self._inflight = task
        try:
            done, _ = await asyncio.wait({task}, timeout=self._config.decision_timeout_s)
        except asyncio.CancelledError:
            task.cancel()
            raise
        finally:
            self._inflight = None
        if not done:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise DeciderError(DECIDER_TIMEOUT, f"no answer within {self._config.decision_timeout_s:g}s")
        if task.cancelled():
            if self._superseded:
                raise _Superseded()
            raise DeciderError(DECIDER_FAILED, "the decider call was cancelled")
        error = task.exception()
        if error is not None:
            if isinstance(error, DeciderError):
                raise error
            raise DeciderError(DECIDER_FAILED, f"{type(error).__name__}: {error}")
        reply = task.result()
        if not isinstance(reply, ToolBrainReply):
            raise DeciderError(DECIDER_FAILED, "the decider returned no plan")
        return reply

    def _read(self, wanted: InspectionRequest, state: UiState, catalog: Mapping[str, Any]) -> Mapping[str, Any]:
        """Lecture ciblée **permise seulement** parmi `INSPECTION_READS` ; un id inconnu est refusé par la lecture."""

        refused = {"schema": "tool_brain.inspection/1", "ok": False, "id": (wanted.id or "")[:80]}
        if wanted.read not in INSPECTION_READS:
            return {**refused, "code": "unknown_read", "detail": f"allowed: {', '.join(INSPECTION_READS)}"}
        if wanted.read == "get_queue_state":
            return get_queue_state(self._queue() if self._queue else None)
        if not wanted.id:
            return {**refused, "code": "missing_id", "detail": f"{wanted.read} needs an id"}
        if wanted.read == "get_information_on":
            return get_information_on(state, wanted.id)
        if wanted.read == "list_related":
            return list_related(state, wanted.id)
        return get_available_actions(catalog, state, wanted.id)

    def _verdict(self, action: ProposedAction, fresh: UiState, observed_state: UiState) -> ActionVerdict:
        verdict = validate_call(action.server, action.tool, action.arguments, fresh, observed=observed_state.ref())
        if verdict.ok:
            return ActionVerdict(action, WOULD_APPLY, (), verdict.revision_drift)
        return ActionVerdict(action, REJECTED, tuple(item.to_dict() for item in verdict.refusals),
                             verdict.revision_drift)

    def _intents_for(self, pending: _Pending, state: UiState) -> list[Mapping[str, Any]]:
        """Intentions du tour réveillé, avec la validité de leurs refs **maintenant** (jamais une autorité)."""

        if self._intents is None or not pending.conversation_id:
            return []
        try:
            rows = list(self._intents(pending.conversation_id, pending.correlation_id))[-8:]
        except Exception as exc:  # noqa: BLE001 - capture: intents are a hint; the decision goes on without them
            self.trace("tool_brain.intents_unreadable", "Intentions illisibles : décision sans elles", level="warning",
                        data={"error_class": type(exc).__name__})
            return []
        enriched: list[Mapping[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                draft = UiIntentDraft.from_payload({key: row[key] for key in ("kind", "refs", "subject", "timing",
                                                                              "paragraph") if key in row})
                item["ref_refusals"] = [refusal.code for refusal in check_intent_refs(draft, state)]
            except ValueError:
                item["ref_refusals"] = ["invalid_intent"]
            enriched.append(item)
        return enriched

    # ------------------------------------------------------------ enregistrement

    def _elapsed_ms(self, started: float) -> int:
        return max(0, int((self._clock() - started) * 1000))

    def _record(self, decision: ToolBrainDecision) -> str:
        decision = replace(decision, seq=int(decision.decision_id.rsplit("-", 1)[1]))
        self._history.append(decision)
        self._counters["decisions"] += 1
        if decision.outcome == COMPLETED:
            self._latencies.append(decision.latency_ms)
            self._counters["completed"] += 1
        if decision.outcome != SUPERSEDED:
            self._last_finished = self._clock()
            self._last_outcome = decision.outcome
        if self._events is not None and self._cycle is not None and "decision" not in self._cycle:
            self._note_decision(decision.decision_id, decision.outcome, decision.model, decision.latency_ms,
                                len(decision.actions), sum(1 for item in decision.actions if item.verdict == REJECTED),
                                decision.error_code)
        decision_ref = self._cycle.get("decision") if self._cycle else None
        self.trace("tool_brain.decision", f"Tool Brain : décision {decision.outcome}",
                    level="info" if decision.outcome in (COMPLETED, SUPERSEDED) else "warning",
                    data={**journal_ref(decision_ref), "decision_id": decision.decision_id, "outcome": decision.outcome,
                          "decider": decision.decider, "latency_ms": decision.latency_ms,
                          "rounds": decision.rounds, "actions": len(decision.actions),
                          "would_apply": sum(1 for item in decision.actions if item.verdict == WOULD_APPLY),
                          "rejected": sum(1 for item in decision.actions if item.verdict == REJECTED),
                          "error_code": decision.error_code, "backoff_s": decision.backoff_s,
                          "wakes": dict(decision.trigger.get("classes", {}))})
        if self._owner_gate is not None:
            try:
                self._owner_gate()  # S8: a decision outcome can change who owns the screen; re-evaluate now, not at the next beat
            except Exception as exc:  # noqa: BLE001 - capture: the heartbeat re-evaluates; a decision must still be recorded
                self.trace("tool_brain.ownership.gate_failed", "Tool Brain : réévaluation de la propriété en échec",
                           level="error", data={"error_class": type(exc).__name__, "detail": str(exc)[:200]})
        return DECIDED

    def _superseded_decision(self, decision_id: str, trigger: Mapping[str, Any], started: float,
                             decider: ToolBrainDecider, digest: str, perception: Any, manifest: Mapping[str, Any],
                             rounds: int, inspections: list[dict[str, Any]]) -> str:
        """Réponse périmée par un réveil urgent : aucune action n'est gardée, la décision suivante part aussitôt."""

        self._counters["superseded"] += 1
        return self._record(ToolBrainDecision(
            decision_id, 0, self._config.mode.value, SUPERSEDED, self._wall(), trigger, decider.name,
            perception_digest=digest, perception_bytes=perception.size_bytes, manifest_tools=len(manifest["tools"]),
            rounds=rounds, inspections=tuple(inspections), latency_ms=self._elapsed_ms(started)))

    def _failure(self, decision_id: str, trigger: Mapping[str, Any], started: float, decider_name: str, outcome: str,
                 code: str, detail: str, pending: _Pending, *, digest: str | None = None,
                 perception_bytes: int = 0) -> str:
        """Panne : backoff croissant, les réveils reviennent dans `_pending` (une seule décision au retour)."""

        self._failures += 1
        schedule = self._config.unavailable_backoff_s if outcome == UNAVAILABLE else self._config.failure_backoff_s
        delay = schedule[min(self._failures - 1, len(schedule) - 1)]
        self._backoff_until = self._clock() + delay
        self._counters["unavailable" if outcome == UNAVAILABLE else "failed"] += 1
        self._counters["backoffs"] += 1
        if self._pending is None:
            self._pending = pending  # rien n'est perdu : un seul essai au retour du backoff
        else:
            self._merge(pending)
        return self._record(ToolBrainDecision(
            decision_id, 0, self._config.mode.value, outcome, self._wall(), trigger, decider_name,
            perception_digest=digest, perception_bytes=perception_bytes, latency_ms=self._elapsed_ms(started),
            error_code=code, error_detail=detail[:300], backoff_s=delay))

    def _merge(self, older: _Pending) -> None:
        current = self._pending
        assert current is not None
        for key, count in older.classes.items():
            current.classes[key] = current.classes.get(key, 0) + count
        current.wakes += older.wakes
        current.invalidated = [*older.invalidated, *current.invalidated][:MAX_INVALIDATIONS_IN_TRIGGER]
        current.first_at = min(current.first_at, older.first_at)
        if older.first_wall is not None:
            current.first_wall = min(current.first_wall or older.first_wall, older.first_wall)
        current.urgent = current.urgent or older.urgent
        for reason in older.reasons:
            if len(current.reasons) < MAX_REASONS and reason not in current.reasons:
                current.reasons.append(reason)

    # ------------------------------------------------------------ évènements de conversation (S9)

    def _note_wake(self, pending: _Pending) -> None:
        assert self._events is not None and self._cycle is not None
        classes = sorted(item.value for item in pending.classes)
        self._cycle["wake"] = self._events.wake(
            self._events.next_id("twk"), wake_class=",".join(classes),
            source="tick" if classes == [WakeClass.TICK.value] else "event", reasons=tuple(pending.reasons),
            conversation_id=pending.conversation_id, correlation_id=pending.correlation_id, at=pending.first_wall)

    def _note_inspection(self, entry: Mapping[str, Any], index: int) -> None:
        if self._events is None or self._cycle is None:
            return
        pending: _Pending = self._cycle["pending"]
        self._events.inspect(self._cycle["decision_id"], index, str(entry.get("read")), ok=bool(entry.get("ok")),
                             code=entry.get("code"), conversation_id=pending.conversation_id,
                             correlation_id=pending.correlation_id,
                             parent=self._cycle.get("snapshot") or self._cycle.get("wake"))

    def _note_decision(self, decision_id: str, outcome: str, model: str, latency_ms: int, actions: int, rejected: int,
                       code: str | None) -> None:
        if self._events is None or self._cycle is None:
            return
        pending: _Pending = self._cycle["pending"]
        self._cycle["decision"] = self._events.decision(
            decision_id, status=outcome, model=model, duration_ms=latency_ms, actions=actions, rejected=rejected,
            code=code, conversation_id=pending.conversation_id, correlation_id=pending.correlation_id,
            parent=self._cycle.get("snapshot") or self._cycle.get("wake")) or ""

    def trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None,
               once: str | None = None) -> None:
        if once is not None:
            if once in self._said_once:
                return
            self._said_once.add(once)
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - argued silence: observability never breaks the decision cycle
            pass


class _Superseded(Exception):
    """Interne : l'appel au décideur a été annulé par un réveil urgent."""


__all__ = [
    "ActionVerdict", "BACKOFF", "COALESCING", "COMPLETED", "DECIDED", "DECISION_SCHEMA", "FAILED", "IDLE", "OFF",
    "RATE_LIMITED", "REJECTED", "SUPERSEDED", "ToolBrainConfig", "ToolBrainDecision", "ToolBrainMode",
    "ToolBrainRuntime", "UNAVAILABLE", "UNCHANGED", "WOULD_APPLY", "WakeClass",
]
