"""La vie d'une séance PRESENTATION, racontée dans la ligne de temps canonique (Slice 10).

Handoff `jarvis-presentation-interaction-mode`, décisions P6 et R4 de
`docs/06-resolved-architecture.md`. Un adaptateur, et rien d'autre : il reçoit
le cycle de vie des services de Presentation par leurs ports optionnels
(`PreparationLifecycle`, `AttentionLifecycle`) et les décisions du coordinateur,
et les enregistre comme Conversation Events par le relais de Voice
(`ConversationEventForwarder`). Le journal d'exécution reste la trace ; ces
événements sont posés **à côté**, jamais à sa place (R6.6).

## Correspondance

| Fait | Événement |
|---|---|
| préparation admise | `subagent.started` (contenu = étiquette des capacités) |
| préparation rangée | `subagent.finished` |
| échec, délai dépassé | `subagent.failed` (`status` `failed` / `timeout` / `normalise_failed`) |
| sacrifiée, retirée avec la séance | `subagent.stopped` (`status` `preempted` / `retired` / `cancelled`) |
| entrée, sortie, refus d'entrée | `system.mode.changed` |
| point d'attention levé | `system.attention.raised` |
| point retiré (fin de séance, éviction) | `system.attention.cleared` |

La parole retenue par la politique (`mouth.speech.superseded`,
`reason=presentation_withheld`) est posée par `SpeechScheduler`, qui possède
déjà les spans de la bouche.

## Ce qui n'y entre jamais

**Rien de ce qui a été dit dans la salle.** Une préparation porte l'étiquette de
ses capacités (`fact_verification`), jamais le texte de son déclencheur ; les
trois types `system.*` interdisent tout contenu par contrat. Les attributs sont
pris dans la liste blanche existante.

## Conversation

La conversation est celle de la voix **vivante**, relue à chaque fait
(`conversation_id` est une fonction), jamais inférée d'un libellé ou d'une
heure (`docs/conversation-events.md`, *Sub-agent mapping rule*). Sans
conversation connue, rien n'est enregistré et le compte le dit. Une fermeture
part dans la conversation de son ouverture : un span ne change pas de
conversation en route.

## Identité

Les numéros de travail (`prep-<génération>-<n>`) et de point d'attention
repartent de zéro à chaque séance. L'identité d'un fait porte donc l'identifiant
de séance PRESENTATION à côté : `task_id = "<séance>/<travail>"`, et le numéro
nu voyage dans `attributes.job_id`.

## Discipline

`record()` est synchrone et ne lève pas ; chaque méthode publique d'ici non
plus. Aucun `trace_ref` : les lignes de journal voisines ne portent pas
l'identifiant de l'événement, et une jointure promise qui ne se fait pas
serait pire que pas de jointure. Une panne se compte (`counters`) et se dit une fois dans le journal, sans
le texte de l'exception.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime
import time
from typing import Any, Callable

from jarvis.domain.conversation_events import ConversationEventType
from jarvis.domain.v2 import utc_now
from jarvis.runtime.conversation_event_forwarder import optional_id

#: Producteur des événements de Presentation. `voice.*` : la ligne de temps les
#: range dans la lane « Jarvis · voix » (règle de lane des acteurs `system`).
PRODUCER_PRESENTATION = "voice.presentation"

#: `subagent_type` des préparations, le nom du profil d'exécution.
PREPARATION_SUBAGENT_TYPE = "presentation_preparation"

#: Ligne de journal d'un enregistrement raté, comme les autres producteurs Voice.
PRODUCER_FAILED_KIND = "voice.conversation_events.producer_failed"

#: Spans de préparation ouverts qu'on garde en mémoire. Le bassin en tient
#: quatre au plus ; au-delà, c'est une fuite, et la plus ancienne ouverture
#: est oubliée plutôt que de grossir sans fin.
MAX_OPEN_SPANS = 64

_CLOSE_TYPES = {
    "finished": ConversationEventType.SUBAGENT_FINISHED,
    "failed": ConversationEventType.SUBAGENT_FAILED,
    "stopped": ConversationEventType.SUBAGENT_STOPPED,
}


@dataclass(slots=True)
class PresentationTimelineCounters:
    recorded: int = 0
    #: Aucune conversation Voice vivante : rien à quoi rattacher le fait.
    skipped_no_conversation: int = 0
    #: Fermeture sans ouverture enregistrée (ouverture perdue ou refusée).
    skipped_unopened: int = 0
    #: Le relais a refusé ou levé.
    failed: int = 0

    def to_payload(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class _OpenSpan:
    conversation_id: str
    started_at: datetime
    started_monotonic: float


class PresentationTimeline:
    """L'adaptateur de la ligne de temps, partagé par toutes les séances du processus."""

    def __init__(
        self,
        *,
        recorder: Any | None,
        conversation_id: Callable[[], str | None],
        journal: Any | None = None,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._recorder = recorder
        self._conversation_id = conversation_id
        self._journal = journal
        self._clock = clock
        self._monotonic = monotonic
        self._open: OrderedDict[str, _OpenSpan] = OrderedDict()
        self._failure_said = False
        self.counters = PresentationTimelineCounters()

    def for_session(self, session_id: str) -> "PresentationSessionTimeline":
        """Les deux ports d'une séance, liés à son identifiant."""

        return PresentationSessionTimeline(self, session_id)

    # -- préparations --------------------------------------------------------

    def preparation_started(self, session_id: str, job_id: str, *, label: str) -> None:
        task_id = _task_id(session_id, job_id)
        conversation = self._live_conversation()
        if task_id is None or conversation is None:
            return
        now = self._now()
        event_id = self._record(
            ConversationEventType.SUBAGENT_STARTED, conversation_id=conversation, source_ids=(task_id,),
            occurred_at=now, task_id=task_id, span_id=task_id,
            content=str(label)[:256] or None,
            attributes={"subagent_type": PREPARATION_SUBAGENT_TYPE, "background": True, "job_id": job_id},
        )
        if event_id is None:
            return
        self._open[task_id] = _OpenSpan(conversation, now, self._monotonic())
        while len(self._open) > MAX_OPEN_SPANS:
            self._open.popitem(last=False)

    def preparation_ended(self, session_id: str, job_id: str, *, outcome: str, status: str,
                          reason: str | None = None) -> None:
        task_id = _task_id(session_id, job_id)
        event_type = _CLOSE_TYPES.get(outcome)
        opened = self._open.pop(task_id, None) if task_id is not None else None
        if event_type is None or opened is None:
            # Une fermeture sans ouverture rendrait un bloc fantôme : rien.
            self.counters.skipped_unopened += 1
            return
        duration_ms = max(0, int(round((self._monotonic() - opened.started_monotonic) * 1000)))
        attributes: dict[str, object] = {
            "subagent_type": PREPARATION_SUBAGENT_TYPE, "background": True, "job_id": job_id,
            "status": _token(status) or outcome, "duration_ms": duration_ms,
        }
        if _token(reason) is not None:
            attributes["reason"] = _token(reason)
        self._record(
            event_type, conversation_id=opened.conversation_id, source_ids=(task_id,),
            occurred_at=self._now(), task_id=task_id, span_id=task_id, started_at=opened.started_at,
            attributes=attributes,
        )

    # -- points d'attention --------------------------------------------------

    def attention_raised(self, session_id: str, attention_id: str, *, category: str) -> None:
        self._attention(ConversationEventType.SYSTEM_ATTENTION_RAISED, session_id, attention_id,
                        {"kind": _token(category) or "unknown", "source": "fact_check"})

    def attention_cleared(self, session_id: str, attention_id: str, *, category: str, reason: str) -> None:
        self._attention(ConversationEventType.SYSTEM_ATTENTION_CLEARED, session_id, attention_id,
                        {"kind": _token(category) or "unknown", "source": "fact_check",
                         "reason": _token(reason) or "unknown"})

    def _attention(self, event_type: ConversationEventType, session_id: str, attention_id: str,
                   attributes: dict[str, object]) -> None:
        session, attention = optional_id(session_id), optional_id(attention_id)
        conversation = self._live_conversation()
        if session is None or attention is None or conversation is None:
            return
        self._record(event_type, conversation_id=conversation, source_ids=(session, attention),
                     occurred_at=self._now(), attributes=attributes)

    # -- mode ----------------------------------------------------------------

    def mode_changed(self, attempt_id: str, *, kind: str, reason: str, code: str | None = None) -> None:
        """Une décision du coordinateur : entrée, sortie ou refus d'entrée.

        `attempt_id` est l'identifiant de la séance tentée (ouverte ou non) ;
        `reason` distingue les faits d'une même tentative.
        """

        attempt, token = optional_id(attempt_id), _token(reason)
        conversation = self._live_conversation()
        if attempt is None or token is None or conversation is None:
            return
        attributes: dict[str, object] = {"kind": _token(kind) or "unknown", "reason": token,
                                         "source": "voice"}
        if _token(code) is not None:
            attributes["code"] = _token(code)
        self._record(ConversationEventType.SYSTEM_MODE_CHANGED, conversation_id=conversation,
                     source_ids=(attempt, token), occurred_at=self._now(), attributes=attributes)

    # -- lecture -------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        return {**self.counters.to_payload(), "open_spans": len(self._open)}

    # -- mécanique -----------------------------------------------------------

    def _live_conversation(self) -> str | None:
        try:
            conversation = optional_id(self._conversation_id())
        except Exception:  # noqa: BLE001 - une lecture ratée vaut « pas de conversation »
            conversation = None
        if conversation is None:
            self.counters.skipped_no_conversation += 1
        return conversation

    def _now(self) -> datetime:
        return self._clock()

    def _record(self, event_type: ConversationEventType, *, conversation_id: str,
                source_ids: tuple[str, ...], occurred_at: datetime, **fields: Any) -> str | None:
        recorder = self._recorder
        if recorder is None:
            return None
        try:
            event_id = recorder.record(event_type, producer=PRODUCER_PRESENTATION,
                                       conversation_id=conversation_id, source_ids=source_ids,
                                       occurred_at=occurred_at, **fields)
        except Exception as exc:  # noqa: BLE001 - l'instrumentation ne change jamais la séance
            self.counters.failed += 1
            self._say_failure(event_type, type(exc).__name__)
            return None
        if event_id is None:
            # Invalide, répété ou relais plein : le relais l'a déjà compté et dit.
            return None
        self.counters.recorded += 1
        return event_id

    def _say_failure(self, event_type: ConversationEventType, exception_type: str) -> None:
        if self._journal is None or self._failure_said:
            return
        self._failure_said = True
        try:
            self._journal.emit(PRODUCER_FAILED_KIND, "Conversation event not recorded", level="warning",
                               data={"producer": PRODUCER_PRESENTATION, "event_type": event_type.value,
                                     "exception_type": exception_type})
        except Exception:  # noqa: BLE001
            # Intentionnel : double panne (relais et journal) ; le compteur reste.
            pass


class PresentationSessionTimeline:
    """Les ports d'une séance : `PreparationLifecycle` et `AttentionLifecycle`."""

    __slots__ = ("_timeline", "_session_id")

    def __init__(self, timeline: PresentationTimeline, session_id: str) -> None:
        self._timeline = timeline
        self._session_id = session_id

    def preparation_started(self, job_id: str, *, label: str) -> None:
        self._timeline.preparation_started(self._session_id, job_id, label=label)

    def preparation_ended(self, job_id: str, *, outcome: str, status: str, reason: str | None = None) -> None:
        self._timeline.preparation_ended(self._session_id, job_id, outcome=outcome, status=status, reason=reason)

    def attention_raised(self, attention_id: str, *, session_id: str, category: str) -> None:
        self._timeline.attention_raised(session_id, attention_id, category=category)

    def attention_cleared(self, attention_id: str, *, session_id: str, category: str, reason: str) -> None:
        self._timeline.attention_cleared(session_id, attention_id, category=category, reason=reason)


def _task_id(session_id: object, job_id: object) -> str | None:
    session, job = optional_id(session_id), optional_id(job_id)
    return None if session is None or job is None else f"{session}/{job}"


def _token(value: object) -> str | None:
    """Un jeton court et sans espace, ou rien. Jamais une phrase."""

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 64 or any(ch.isspace() for ch in text):
        return None
    return text


__all__ = [
    "MAX_OPEN_SPANS",
    "PREPARATION_SUBAGENT_TYPE",
    "PRODUCER_PRESENTATION",
    "PresentationSessionTimeline",
    "PresentationTimeline",
    "PresentationTimelineCounters",
]
