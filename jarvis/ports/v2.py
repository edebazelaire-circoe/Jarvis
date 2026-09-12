from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, Protocol, TypeGuard, runtime_checkable

from jarvis.domain.brain_context import BrainContext
from jarvis.domain.v2 import (
    BrainEvent,
    BrainTurnInput,
    BrainTurnResult,
    BrainWorkingState,
    Conversation,
    ConversationTurn,
    Device,
    HistoryRecord,
    Job,
    JobProgress,
    Notification,
    PlaybackCursor,
    ProtocolEnvelope,
    ScheduledItem,
    SpeechRequest,
)


class Clock(Protocol):
    def now(self) -> datetime: ...
    async def sleep(self, seconds: float) -> None: ...


class StateRepository(Protocol):
    async def initialize(self) -> None: ...
    async def save_device(self, value: Device) -> None: ...
    async def save_conversation(self, value: Conversation) -> None: ...
    async def get_conversation(self, conversation_id: str) -> Conversation | None: ...
    async def save_turn(self, value: ConversationTurn) -> None: ...
    async def list_turns(self, conversation_id: str, *, limit: int = 20) -> Sequence[ConversationTurn]: ...
    async def save_job(self, value: Job) -> None: ...
    async def list_jobs(self, *, status: str | None = None) -> Sequence[Job]: ...
    async def save_scheduled_item(self, value: ScheduledItem) -> None: ...
    async def list_scheduled_items(self, *, active_only: bool = False) -> Sequence[ScheduledItem]: ...
    async def save_notification(self, value: Notification) -> None: ...
    async def list_notifications(self, *, state: str | None = None) -> Sequence[Notification]: ...
    async def close(self) -> None: ...


class HistoryStore(Protocol):
    async def append(self, record: HistoryRecord) -> bool: ...
    async def read(self, *, conversation_id: str | None = None) -> Sequence[HistoryRecord]: ...
    async def cleanup(self, *, older_than: datetime) -> int: ...


class EventSink(Protocol):
    async def publish(self, event: ProtocolEnvelope) -> None: ...


class JobWorker(Protocol):
    async def execute(self, job: Job) -> dict[str, object]: ...
    async def cancel(self, job_id: str) -> None: ...


class JobProgressSink(Protocol):
    """Couture d'avancement neutre, remise a un worker pendant son execution.

    Possedee par `JobService` : le worker ne connait ni `CoreEventBus`, ni le
    `work_id` du cerveau, ni le contrat de transport. Il constate, le service
    publie (spec section 13).

    Concurrence : l'instance remise est confinee a la tache du job. Le debit
    est borne par l'implementation, pas par l'appelant — un worker peut appeler
    `emit` aussi souvent qu'il veut sans risquer de saturer le bus.
    """

    async def emit(self, job_id: str, progress: JobProgress) -> None: ...


@runtime_checkable
class ProgressReportingJobWorker(Protocol):
    """Worker sachant rendre compte de son avancement.

    Capacite **optionnelle**, declaree par une methode distincte plutot que par
    un elargissement de `JobWorker.execute` : les workers existants restent
    valides sans modification, et la detection reste structurelle
    (`isinstance`) au lieu de reposer sur une inspection de signature.

    Un worker qui implemente cette capacite n'a pas besoin d'implementer aussi
    `execute` : `JobService` appelle l'une **ou** l'autre.
    """

    async def execute_with_progress(self, job: Job, progress: JobProgressSink) -> dict[str, object]: ...
    async def cancel(self, job_id: str) -> None: ...


class WorkCanceller(Protocol):
    """Arret du travail executable rattache a un `work_id` du cerveau.

    Seule couture par laquelle l'orchestrateur peut arreter du travail. Elle
    est designee, jamais globale : `cancel_work` n'arrete que ce qui porte ce
    `work_id` exact, et rend les identifiants de job effectivement vises, pour
    que la decision reste verifiable au diagnostic.

    Port plutot qu'appel direct a `JobService` : l'orchestrateur ne doit pas
    dependre du cycle de vie des jobs pour publier une revision d'intention, et
    un deploiement headless peut ne cabler aucun executeur.
    """

    async def cancel_work(self, work_id: str) -> Sequence[str]: ...


class NotificationDelivery(Protocol):
    async def deliver(self, notification: Notification) -> None: ...


class WakeWordBackend(Protocol):
    async def detections(self) -> AsyncIterator[str]: ...
    async def suspend(self) -> None: ...
    async def suspend_for_active_session(self) -> None: ...
    async def resume(self) -> None: ...
    async def close(self) -> None: ...


class RealtimeSession(Protocol):
    async def send_audio(self, pcm: bytes) -> None: ...
    async def finish_input(self) -> bool:
        """Commit buffered audio and request a response; False if too short."""
        ...
    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None: ...
    async def send_context(self, text: str) -> None: ...
    async def keepalive(self) -> None:
        """Maintenir la connexion pendant une attente longue (outil lent)."""
        ...
    async def events(self) -> AsyncIterator[ProtocolEnvelope]: ...
    async def close(self) -> None: ...


class BrainEventSink(Protocol):
    """Puits des signaux incrementaux emis par un backend cerveau.

    Possede par `BrainOrchestrator` : le backend ne publie jamais lui-meme sur
    `CoreEventBus` (spec section 3). L'orchestrateur reste seul responsable de
    la traduction en `ProtocolEnvelope` `brain.*`.
    """

    async def emit(self, event: BrainEvent) -> None: ...


class BrainBackend(Protocol):
    """Modele fort executant un tour de conversation, vu de facon neutre par Core.

    L'implementation concrete (Control Center, Claude, Codex...) vit dans
    `jarvis/adapters` et est injectee au composition root (Decisions 19 et 23).

    Concurrence : `run_turn` est appele dans une tache asyncio possedee par
    l'orchestrateur et doit etre annulable par `CancelledError`. L'etat passe
    en argument est immuable ; le backend ne le modifie pas, il decrit ce qu'il
    observe via `emit` et rend une issue.
    """

    async def run_turn(
        self,
        turn: BrainTurnInput,
        state: BrainWorkingState,
        emit: BrainEventSink,
    ) -> BrainTurnResult: ...


@runtime_checkable
class ContextAwareBrainBackend(Protocol):
    """Backend cerveau sachant recevoir le contexte complet assemblé par Core.

    Capacité **optionnelle** (handoff work-state, tâche 12), déclarée par une
    méthode distincte comme `ProgressReportingJobWorker` : `BrainBackend` n'est
    pas élargi, ses doubles de test restent valides, et un backend qui ne la
    déclare pas reçoit `run_turn(turn, state, emit)` exactement comme avant.
    Détection structurelle par `supports_brain_context`.

    `context.state` est l'état passé à `run_turn` ; `context.work` est
    l'instantané borné du travail en cours, lu par Core au moment du tour
    (`None` si Core n'a pas pu le lire). Mêmes règles de concurrence et
    d'annulation que `BrainBackend.run_turn`.
    """

    async def run_turn_with_context(
        self,
        turn: BrainTurnInput,
        context: BrainContext,
        emit: BrainEventSink,
    ) -> BrainTurnResult: ...


def supports_brain_context(backend: object) -> TypeGuard[ContextAwareBrainBackend]:
    """Indiquer si le backend sait recevoir le `BrainContext` de Core."""

    return isinstance(backend, ContextAwareBrainBackend)


@runtime_checkable
class RealtimeOutputControl(Protocol):
    """Controles de sortie semantiques d'une surface vocale.

    Port distinct et optionnel : `RealtimeSession` n'est deliberement pas
    elargi (Decision 22), car toutes ses implementations et ses doubles de test
    devraient sinon changer, et Gemini Live reste sur le chemin legacy
    (Decision 21). Une pile vocale annonce cette capacite en implementant ces
    trois methodes ; le runtime la teste via `supports_output_control` et refuse
    le mode continu quand elle est absente.

    Aucun JSON fournisseur ne traverse ce port : `speak` rend un identifiant de
    sortie opaque, utilise ensuite pour la comptabilite d'interruption.
    """

    async def speak(self, request: SpeechRequest) -> str:
        """Faire dire le texte du cerveau tel quel et rendre l'identifiant de sortie.

        Ne doit pas fabriquer un faux tour utilisateur (spec section 8).
        """
        ...

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        """Interrompre la generation en cours ; sans effet si rien ne joue."""
        ...

    async def truncate(self, cursor: PlaybackCursor) -> None:
        """Aligner l'historique fournisseur sur ce qui a reellement ete entendu."""
        ...


def supports_output_control(session: object) -> TypeGuard[RealtimeOutputControl]:
    """Indiquer si la session active sait piloter la sortie vocale du cerveau.

    Verification structurelle : elle atteste la presence des trois methodes,
    pas la conformite de leurs signatures. C'est suffisant comme garde de
    configuration, l'appelant devant de toute facon gerer les erreurs d'appel.
    """

    return isinstance(session, RealtimeOutputControl)


def supports_reflex(session: object) -> bool:
    """Indiquer si la surface sait accuser réception d'une demande d'elle-même.

    Capacité optionnelle, testée structurellement comme la précédente :
    `speak_reflex(transcript=..., avoid=...)` rend un identifiant de sortie
    opaque, et une pile qui ne l'a pas se tait simplement en attendant le
    cerveau.
    """

    return callable(getattr(session, "speak_reflex", None))


JobFactory = Callable[[ScheduledItem], Awaitable[Job | None]]


class DiagnosticSink(Protocol):
    """Puits de diagnostic neutre pour le coeur applicatif.

    `jarvis/core` doit pouvoir signaler une anomalie interne (eviction d'un
    abonne du bus, par exemple) sans connaitre le journal concret. La signature
    reprend celle de `RuntimeJournal.emit` afin que le composition root puisse
    injecter le journal runtime directement, sans adaptateur intermediaire.
    """

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None: ...
