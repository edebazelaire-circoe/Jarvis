"""Le travail en cours, vu par le cerveau (handoff work-state, tâche 12).

Deux pièces Core, séparées de `BrainOrchestrator` pour qu'il reste le seul
propriétaire des tours :

- `WorkAttentionPolicy` : abonnée à `core.work.updated`, elle relève les
  changements inattendus d'un travail actif (échec, interruption, blocage).
  Elle les retient pour le prochain tour du cerveau, les signale au
  diagnostic et peut réveiller la cognition par un rappel injecté. Elle ne
  produit **jamais** de parole : un changement d'état n'est pas une prise de
  parole (Décision D17), la parole reste une `SpeechRequest` que seul le
  cerveau émet, ordonnée ensuite par le `SpeechScheduler` de Voice.
- `BrainContextBuilder` : lit `WorkStateReader.snapshot()` — la source même
  de `GET /v1/work/snapshot` — et en tire le `BrainWorkContext` borné de
  chaque tour, avec les changements relevés depuis le tour précédent.

Aucune des deux ne touche l'état public du cerveau, ses révisions
d'intention ni le travail qu'il a nommé : l'annulation reste une décision
explicite du cerveau désignant un `work_id`.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
import time

from jarvis.core.v2_services import NullDiagnosticSink, SystemClock
from jarvis.core.work_state import CORE_WORK_UPDATED
from jarvis.domain.brain_context import (
    MAX_BRAIN_WORK_ATTENTION,
    BrainWorkContext,
    WorkAttention,
    build_brain_work_context,
    needs_attention,
)
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.domain.work_state import WorkItem, WorkStatus
from jarvis.ports.v2 import Clock, DiagnosticSink
from jarvis.ports.work_state import WorkStateReader

WORK_ATTENTION_KIND = "core.work.attention"
WORK_ATTENTION_WAKE_FAILED_KIND = "core.work.attention_wake_failed"
WORK_ATTENTION_INVALID_EVENT_KIND = "core.work.attention_invalid_event"
BRAIN_WORK_CONTEXT_KIND = "core.brain.work_context"
BRAIN_WORK_CONTEXT_FAILED_KIND = "core.brain.work_context_failed"

#: Écart minimal entre deux réveils de la cognition. Pendant ce délai, les
#: changements s'accumulent et le prochain tour les reçoit quand même.
DEFAULT_WAKE_INTERVAL_S = 60.0
#: Diagnostics `core.work.attention` par minute ; au-delà ils sont comptés
#: (`suppressed`) : une interruption de processus peut en produire des dizaines.
DEFAULT_ATTENTION_DIAGNOSTICS_PER_MINUTE = 20
#: File d'abonnement au bus : la politique ne fait aucune entrée-sortie, elle
#: se vide bien plus vite qu'un renvoi complet de 64 éléments ne la remplit.
#: Core l'abonne en mode tolérant (`CoreEventBus.subscribe(lossy=True)`) : une
#: saturation perd l'événement le plus ancien, jamais l'abonnement.
ATTENTION_QUEUE_SIZE = 512

#: Réveil de la cognition : reçoit les changements retenus, sans les consommer.
WakeCallback = Callable[[tuple[WorkAttention, ...]], Awaitable[None]]


class WorkAttentionPolicy:
    """Politique Core des changements d'état de travail.

    Règle : seul un travail **actif** qui passe en `failed`, `interrupted` ou
    `blocked` est retenu (`needs_attention`). Une progression, une réussite,
    une annulation ou une création déjà terminée (renvoi après redémarrage)
    ne le sont pas.

    Retenir, c'est garder le changement — au plus `MAX_BRAIN_WORK_ATTENTION`,
    un par travail, le plus récent gagnant — jusqu'au tour du cerveau qui le
    reçoit dans son contexte. Seul ce qui a été **remis** est consommé
    (`take_delivered`) : une note qui n'a pas tenu dans le budget du contexte
    reste en attente pour le tour suivant. `take_pending` vide tout d'un coup
    et ne sert qu'aux appelants qui remettent eux-mêmes l'intégralité.

    Réveiller est optionnel (`wake`) et borné : au plus un réveil par
    `wake_interval_s`, jamais deux en vol ; un réveil manqué n'est pas
    rattrapé, le changement attend le tour suivant. Le rappel ne consomme
    rien : si le réveil ouvre un tour, c'est ce tour qui reçoit les
    changements.

    Concurrence : tout s'exécute dans la boucle de Core ; `consider` est
    synchrone et sans entrée-sortie.
    """

    def __init__(
        self,
        *,
        diagnostics: DiagnosticSink | None = None,
        clock: Clock | None = None,
        wake: WakeCallback | None = None,
        wake_interval_s: float = DEFAULT_WAKE_INTERVAL_S,
        diagnostics_per_minute: int = DEFAULT_ATTENTION_DIAGNOSTICS_PER_MINUTE,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._clock: Clock = clock or SystemClock()
        self._wake = wake
        self._wake_interval_s = wake_interval_s
        self._diagnostics_per_minute = diagnostics_per_minute
        self._monotonic = monotonic
        self._pending: OrderedDict[tuple[str, str], WorkAttention] = OrderedDict()
        self._last_wake: float | None = None
        self._wake_task: asyncio.Task[None] | None = None
        self._window_start: float | None = None
        self._window_count = 0
        self._suppressed = 0
        self._reported_errors: set[str] = set()
        self.noticed_total = 0
        self.wake_total = 0

    @property
    def pending(self) -> tuple[WorkAttention, ...]:
        return tuple(self._pending.values())

    def take_pending(self) -> tuple[WorkAttention, ...]:
        """Rendre et effacer les changements retenus : ils partent avec un tour."""

        notes = tuple(self._pending.values())
        self._pending.clear()
        return notes

    def take_delivered(self, delivered: tuple[WorkAttention, ...]) -> int:
        """Consommer les seules notes effectivement remises ; rend leur nombre.

        Ce qui n'a pas tenu dans le budget du contexte reste en attente : un
        échec n'est jamais effacé sans que le cerveau l'ait appris. Une note
        remplacée entre-temps par une plus récente (même travail, révision
        plus haute) reste aussi : c'est le nouveau changement qui attend.
        """

        consumed = 0
        for note in delivered:
            current = self._pending.get(note.key)
            if current is not None and current.revision <= note.revision:
                del self._pending[note.key]
                consumed += 1
        return consumed

    def consider(self, envelope: ProtocolEnvelope) -> WorkAttention | None:
        """Examiner un événement du bus ; rend le changement retenu, s'il y en a un."""

        if envelope.message_type != CORE_WORK_UPDATED:
            return None
        payload = envelope.payload
        try:
            item = WorkItem.from_payload(payload["item"])
            raw_previous = payload.get("previous_status")
            previous = WorkStatus(raw_previous) if raw_previous else None
        except (KeyError, TypeError, ValueError) as exc:
            self._report_once(
                f"invalid:{type(exc).__name__}",
                WORK_ATTENTION_INVALID_EVENT_KIND,
                "événement d'état de travail illisible, ignoré par la politique",
                data={"error": type(exc).__name__},
            )
            return None
        if not needs_attention(previous, item.status):
            return None
        note = WorkAttention.from_item(item, previous_status=previous, noticed_at=self._clock.now())  # type: ignore[arg-type]
        self._pending.pop(note.key, None)
        self._pending[note.key] = note
        while len(self._pending) > MAX_BRAIN_WORK_ATTENTION:
            self._pending.popitem(last=False)
        self.noticed_total += 1
        wake = self._should_wake()
        self._note(note, wake=wake)
        if wake:
            self._start_wake()
        return note

    async def run(self, queue: asyncio.Queue[ProtocolEnvelope]) -> None:
        """Consommer le bus jusqu'à annulation ; une erreur ne tue pas la boucle."""

        while True:
            envelope = await queue.get()
            try:
                self.consider(envelope)
            except Exception as exc:  # garde-fou : la politique ne doit jamais s'arrêter
                self._report_once(
                    f"consider:{type(exc).__name__}",
                    WORK_ATTENTION_INVALID_EVENT_KIND,
                    "la politique d'état de travail a échoué sur un événement",
                    data={"error": type(exc).__name__},
                )

    async def stop(self) -> None:
        task, self._wake_task = self._wake_task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # -- réveil -------------------------------------------------------------

    def _should_wake(self) -> bool:
        if self._wake is None:
            return False
        if self._wake_task is not None and not self._wake_task.done():
            return False
        now = self._monotonic()
        return self._last_wake is None or now - self._last_wake >= self._wake_interval_s

    def _start_wake(self) -> None:
        self._last_wake = self._monotonic()
        self.wake_total += 1
        self._wake_task = asyncio.create_task(self._run_wake(self.pending), name="jarvis-work-attention-wake")

    async def _run_wake(self, notes: tuple[WorkAttention, ...]) -> None:
        try:
            await self._wake(notes)  # type: ignore[misc]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._report_once(
                f"wake:{type(exc).__name__}",
                WORK_ATTENTION_WAKE_FAILED_KIND,
                "réveil de la cognition en échec ; le changement attend le prochain tour",
                level="warning",
                data={"error": type(exc).__name__},
            )

    # -- diagnostic ---------------------------------------------------------

    def _note(self, note: WorkAttention, *, wake: bool) -> None:
        now = self._monotonic()
        if self._window_start is None or now - self._window_start >= 60.0:
            self._window_start, self._window_count = now, 0
        if self._window_count >= self._diagnostics_per_minute:
            self._suppressed += 1
            return
        self._window_count += 1
        data = {
            "source": note.source,
            "external_id": note.external_id,
            "status": note.status.value,
            "previous_status": note.previous_status.value,
            "error_class": note.error_class,
            "work_id": note.work_id,
            "revision": note.revision,
            "pending": len(self._pending),
            "wake": wake,
        }
        if self._suppressed:
            data["suppressed"], self._suppressed = self._suppressed, 0
        self._emit(
            WORK_ATTENTION_KIND,
            "changement inattendu d'un travail, retenu pour le cerveau (aucune parole)",
            level="warning" if note.status is not WorkStatus.BLOCKED else "info",
            data=data,
        )

    def _report_once(self, key: str, kind: str, message: str, *, level: str = "info", data: dict) -> None:
        if key in self._reported_errors:
            return
        if len(self._reported_errors) >= 64:
            self._reported_errors.clear()
        self._reported_errors.add(key)
        self._emit(kind, message, level=level, data=data)

    def _emit(self, kind: str, message: str, *, level: str, data: dict) -> None:
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            # Un journal indisponible ne doit jamais arrêter la politique.
            pass


class BrainContextBuilder:
    """Assembler, à chaque tour, le travail en cours que Core remet au cerveau.

    Même source que l'UI : `WorkStateReader.snapshot()` du `WorkStateStore`,
    dont `store_id` et `revision` accompagnent le contexte. Une lecture qui
    échoue rend `None` — le tour part sans contexte de travail — et laisse
    les changements retenus en place pour le tour suivant.
    """

    def __init__(
        self,
        *,
        reader: WorkStateReader,
        store_id: str | None = None,
        attention: WorkAttentionPolicy | None = None,
        diagnostics: DiagnosticSink | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._reader = reader
        self._store_id = store_id
        self._attention = attention
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._clock: Clock = clock or SystemClock()
        self._reported_errors: set[str] = set()

    async def work_context(self, *, correlation_id: str | None = None) -> BrainWorkContext | None:
        try:
            snapshot = await self._reader.snapshot()
            attention = self._attention.pending if self._attention is not None else ()
            context = build_brain_work_context(snapshot, now=self._clock.now(), store_id=self._store_id, attention=attention)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            name = type(exc).__name__
            if name not in self._reported_errors and len(self._reported_errors) < 64:
                self._reported_errors.add(name)
                self._emit(
                    BRAIN_WORK_CONTEXT_FAILED_KIND,
                    "état de travail illisible : le tour part sans contexte de travail",
                    level="warning",
                    data={"correlation_id": correlation_id, "error": name},
                )
            return None
        if self._attention is not None:
            # Consommés seulement une fois le contexte construit, et seulement
            # ceux qu'il porte vraiment : un échec plus haut, ou un budget de
            # caractères trop court, les laisse au tour suivant.
            self._attention.take_delivered(context.attention)
        self._emit(
            BRAIN_WORK_CONTEXT_KIND,
            "contexte de travail remis au cerveau",
            level="info",
            data={
                "correlation_id": correlation_id,
                "store_id": context.store_id,
                "revision": context.revision,
                "active_total": context.active_total,
                "finished_total": context.finished_total,
                "listed": len(context.items),
                "attention": len(context.attention),
            },
        )
        return context

    def _emit(self, kind: str, message: str, *, level: str, data: dict) -> None:
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            pass
