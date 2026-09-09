from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timedelta, timezone
from enum import IntEnum, StrEnum
from typing import Any
import uuid

PROTOCOL_VERSION = 1
DEFAULT_DEVICE_ID = "windows-desktop"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class TurnKind(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_REQUEST = "tool_request"
    TOOL_RESULT = "tool_result"
    SYSTEM_EVENT = "system_event"
    ERROR = "error"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ScheduledStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MissedRunPolicy(StrEnum):
    NOTIFY_LATE = "notify_late"
    RUN_IF_RECENT = "run_if_recent"
    SKIP = "skip"
    REQUIRE_CONFIRMATION = "require_confirmation"


class NotificationState(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    EXPIRED = "expired"
    FAILED = "failed"


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class VoiceLifecycleState(StrEnum):
    BACKGROUND = "background"
    ACTIVE = "active"
    CONNECTING = "connecting"
    ERROR = "error"


class AddressingDecision(StrEnum):
    ADDRESSED = "addressed"
    AMBIENT = "ambient"
    UNCERTAIN = "uncertain"


#: Reponse convenue par laquelle le cerveau conclut qu'un tour `UNCERTAIN` ne
#: lui etait pas adresse (Decision 44). La surface ne tranche plus le routage :
#: elle transmet le doute, et c'est cette reponse qui porte le verdict inverse.
#:
#: Constante partagee volontairement : l'hote de l'agent l'ecrit dans la
#: consigne qu'il donne au modele (`jarvis/runtime/control_center.py`), et le
#: backend cerveau la reconnait dans la reponse pour ne rien faire prononcer
#: (`jarvis/adapters/control_center_brain.py`). Deux copies d'une chaine magique
#: se seraient desynchronisees en silence, et le symptome aurait ete Jarvis
#: prononcant « [pas-pour-moi] » a voix haute.
BRAIN_NOT_ADDRESSED_ANSWER = "[pas-pour-moi]"


@dataclass(frozen=True, slots=True)
class Device:
    device_id: str = DEFAULT_DEVICE_ID
    kind: str = "windows-desktop"
    display_name: str = "Windows desktop"
    capabilities: tuple[str, ...] = ()
    last_seen_at: datetime = field(default_factory=utc_now)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.device_id.strip():
            raise ValueError("device_id is required")
        _aware(self.last_seen_at)


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str = field(default_factory=new_id)
    status: ConversationStatus = ConversationStatus.ACTIVE
    originating_device_id: str = DEFAULT_DEVICE_ID
    current_device_id: str = DEFAULT_DEVICE_ID
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    summary: str = ""
    transport_session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.originating_device_id:
            raise ValueError("conversation id and originating device are required")
        _aware(self.created_at)
        _aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    id: str = field(default_factory=new_id)
    conversation_id: str = ""
    kind: TurnKind = TurnKind.USER
    content: str = ""
    created_at: datetime = field(default_factory=utc_now)
    correlation_id: str = field(default_factory=new_id)
    reference_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        _aware(self.created_at)


@dataclass(frozen=True, slots=True)
class Job:
    id: str = field(default_factory=new_id)
    kind: str = ""
    status: JobStatus = JobStatus.PENDING
    requested_by_conversation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    idempotency_key: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("job kind is required")
        _aware(self.created_at)
        for value in (self.started_at, self.completed_at):
            if value is not None:
                _aware(value)


@dataclass(frozen=True, slots=True)
class JobProgress:
    """Fait d'avancement rapporte par un worker (spec section 13).

    Volontairement dépourvu de tout champ de parole : ni texte a dire, ni
    priorite, ni destinataire. « Workers must not directly decide what Jarvis
    says » — un worker constate, le cerveau decide si le constat merite d'etre
    prononce. `public_summary` reste donc un resume **deja sur** pour un
    humain, jamais une phrase que la surface serait tenue de dire.

    Immuable comme le reste du domaine : la valeur traverse la tache du job et
    la boucle de publication sans verrou.
    """

    phase: str = ""
    fraction: float | None = None
    public_summary: str = ""
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.fraction is not None and not 0.0 <= self.fraction <= 1.0:
            raise ValueError("fraction must be between 0 and 1")
        _aware(self.created_at)

    def to_payload(self) -> dict[str, Any]:
        """Part variable de `brain.work.progress` (docs/05).

        Les identifiants (`work_id`, `job_id`) n'appartiennent pas au worker :
        c'est `JobService` qui les ajoute, parce que lui seul sait a quel
        travail le job est rattache.
        """

        return {
            "phase": self.phase or None,
            "fraction": self.fraction,
            "public_summary": self.public_summary,
        }


@dataclass(frozen=True, slots=True)
class ScheduledItem:
    id: str = field(default_factory=new_id)
    kind: str = "reminder"
    status: ScheduledStatus = ScheduledStatus.ACTIVE
    payload: dict[str, Any] = field(default_factory=dict)
    next_fire_at: datetime = field(default_factory=utc_now)
    recurrence_seconds: int | None = None
    missed_run_policy: MissedRunPolicy = MissedRunPolicy.NOTIFY_LATE
    max_lateness_seconds: int | None = None
    last_fire_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    requested_by_conversation_id: str | None = None
    idempotency_key: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        _aware(self.next_fire_at)
        _aware(self.created_at)
        if self.last_fire_at is not None:
            _aware(self.last_fire_at)
        if self.recurrence_seconds is not None and self.recurrence_seconds <= 0:
            raise ValueError("recurrence_seconds must be positive")
        if self.missed_run_policy is MissedRunPolicy.RUN_IF_RECENT and not self.max_lateness_seconds:
            raise ValueError("RUN_IF_RECENT requires max_lateness_seconds")


@dataclass(frozen=True, slots=True)
class Notification:
    id: str = field(default_factory=new_id)
    summary: str = ""
    body: str = ""
    state: NotificationState = NotificationState.PENDING
    priority: NotificationPriority = NotificationPriority.NORMAL
    target_device_id: str = DEFAULT_DEVICE_ID
    originating_reference_id: str | None = None
    delivery_policy: str = "system_notification"
    created_at: datetime = field(default_factory=utc_now)
    delivered_at: datetime | None = None
    expires_at: datetime | None = None
    idempotency_key: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("notification summary is required")
        _aware(self.created_at)
        for value in (self.delivered_at, self.expires_at):
            if value is not None:
                _aware(value)


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    id: str
    kind: TurnKind
    created_at: datetime
    correlation_id: str
    conversation_id: str | None = None
    content: str | None = None
    reference_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _aware(self.created_at)


@dataclass(frozen=True, slots=True)
class ProtocolEnvelope:
    message_type: str
    payload: dict[str, Any]
    correlation_id: str = field(default_factory=new_id)
    protocol_version: int = PROTOCOL_VERSION
    device_id: str = DEFAULT_DEVICE_ID
    conversation_id: str | None = None

    def __post_init__(self) -> None:
        if self.protocol_version != PROTOCOL_VERSION:
            raise ValueError(f"unsupported protocol version: {self.protocol_version}")
        if not self.message_type:
            raise ValueError("message_type is required")


# ---------------------------------------------------------------------------
# Contrats cerveau / parole (handoff realtime-brain, tache 01)
#
# Invariants transverses de ce bloc :
# - Aucun de ces types ne porte de raisonnement cache (Decision 12) : pas de
#   `thoughts`, `reasoning`, `scratchpad`, `chain_of_thought`. Seul l'etat
#   public, destine a l'utilisateur ou au redemarrage, est representable ici.
# - `correlation_id` est la cle de deduplication obligatoire (Decision 24) ;
#   `provider_item_id` reste optionnel et secondaire.
# - Ces valeurs sont immuables (`frozen`) : elles traversent des taches asyncio
#   concurrentes (Voice, orchestrateur cerveau, ordonnanceur de parole) sans
#   verrou. Toute evolution d'etat produit une nouvelle instance, jamais une
#   mutation en place.
# ---------------------------------------------------------------------------


class SpeechKind(StrEnum):
    """Nature publique d'une prise de parole (pilote la politique du planificateur)."""

    ACK = "ack"
    PROGRESS = "progress"
    QUESTION = "question"
    RESULT = "result"
    ERROR = "error"


class SpeechPriority(IntEnum):
    """Ordre de service de la parole.

    Volontairement un `IntEnum` et non un `StrEnum` : l'ordonnancement est la
    semantique porteuse (tache 08), et une comparaison de chaines donnerait un
    ordre alphabetique faux. La forme de transport reste textuelle via
    `label` / `from_label`, conformement a `docs/05-event-contracts.md`.
    """

    LOW = 10
    NORMAL = 20
    HIGH = 30
    IMMEDIATE = 40

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def from_label(cls, value: str) -> SpeechPriority:
        try:
            return cls[value.strip().upper()]
        except KeyError as exc:
            raise ValueError(f"unknown speech priority: {value!r}") from exc


class SpeechProvenance(StrEnum):
    """Origine d'une sortie vocale, persistee avec le tour assistant (spec section 15).

    Permet au cerveau de savoir ce que l'utilisateur a reellement entendu et
    d'eviter les doublons de progression.
    """

    BRAIN = "brain.speech"
    SURFACE_REFLEX = "surface.reflex"
    SYSTEM_NOTIFICATION = "system.notification"


class BrainTurnSource(StrEnum):
    """Surface d'origine d'un tour utilisateur faisant autorite."""

    REALTIME = "realtime"
    TEXT = "text"
    SYSTEM = "system"


class BrainRunStatus(StrEnum):
    """Issue d'une execution `BrainBackend.run_turn`."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BrainEventKind(StrEnum):
    """Evenements qu'un backend cerveau peut emettre pendant un tour.

    Le backend n'ecrit jamais sur le bus Core : l'orchestrateur traduit ces
    valeurs en `brain.*` `ProtocolEnvelope` (spec section 3).

    `SUPERSEDED` et `CANCELLED` sont les deux seules facons de retirer du
    travail, et toutes deux exigent une decision **explicite** du cerveau
    nommant le `work_id` vise (spec section 12, point 9 : « jobs continue
    unless the brain explicitly cancels them »). Elles ne sont pas
    interchangeables :

    - `SUPERSEDED` : le travail continue, mais la parole deja en file a son
      sujet ne decrit plus l'intention courante ;
    - `CANCELLED` : le travail s'arrete, et plus rien ne doit etre dit a son
      sujet.
    """

    ACCEPTED = "accepted"
    PROGRESS = "progress"
    SPEECH = "speech"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


# Parole dont la verite s'evapore : une progression ou un accuse decrivent un
# instant, pas un fait durable. Un resultat, une question ou une erreur restent
# vrais tant que le cerveau ne les a pas retires, donc ils n'ont pas de TTL par
# defaut. Cette liste est la source unique : le coeur l'utilise pour dater la
# peremption, l'ordonnanceur de parole pour jeter ce qui n'est plus vrai.
TRANSIENT_SPEECH_KINDS = (SpeechKind.PROGRESS, SpeechKind.ACK)

# Duree de vie par defaut d'une parole transitoire, en secondes.
#
# Choix : 45 s. Un tour cerveau utile dure de quelques secondes a quelques
# minutes ; une progression vieille de 45 s a donc de bonnes chances d'avoir
# ete depassee par la suivante ou par le resultat, et la prononcer ferait dire
# a Jarvis quelque chose qui n'est plus vrai (Decision 31). Plus court
# perimerait des progressions encore justes pendant qu'une phrase se termine ;
# plus long laisserait la file survivre a l'evenement qu'elle decrit.
DEFAULT_TRANSIENT_SPEECH_TTL_S = 45.0

# Marqueur de livraison porte par les metadonnees d'un tour assistant du
# cerveau. Absent, la phrase a ete dite en entier.
#
# Une sortie coupee par la parole de l'utilisateur (spec section 12) est
# persistee telle quelle - la surface ne reecrit jamais un mot du cerveau
# (Decision 13) - mais marquee ici, avec les millisecondes reellement
# entendues. C'est ce marqueur qui empeche l'historique de pretendre que
# l'utilisateur a entendu l'audio tronque : une phrase partielle n'entre ni
# dans les faits publics connus ni dans les questions posees.
SPEECH_DELIVERY_PARTIAL = "partial"


def _parse_aware(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return _aware(parsed)


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    """Demande de parole publique emise par le cerveau.

    Propriete : le cerveau (Core) redige le texte ; la surface Realtime le
    restitue fidelement sans le reinterpreter (Decisions 02 et 13).
    """

    conversation_id: str
    text: str
    kind: SpeechKind = SpeechKind.PROGRESS
    priority: SpeechPriority = SpeechPriority.NORMAL
    id: str = field(default_factory=new_id)
    correlation_id: str = field(default_factory=new_id)
    work_id: str | None = None
    supersedes_key: str | None = None
    interruptible: bool = True
    expires_at: datetime | None = None
    provenance: SpeechProvenance = SpeechProvenance.BRAIN
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        if not self.text.strip():
            raise ValueError("speech text is required")
        if not self.correlation_id:
            raise ValueError("correlation_id is required")
        _aware(self.created_at)
        if self.expires_at is not None:
            _aware(self.expires_at)
            if self.expires_at <= self.created_at:
                raise ValueError("expires_at must be after created_at")

    @property
    def ordering_key(self) -> tuple[int, datetime]:
        """Cle de tri : priorite decroissante, puis FIFO a priorite egale."""

        return (-int(self.priority), self.created_at)

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and _aware(now) >= self.expires_at

    @property
    def is_transient(self) -> bool:
        """Vrai si la verite portee par cette parole se perime d'elle-meme."""

        return self.kind in TRANSIENT_SPEECH_KINDS

    def with_default_ttl(self, seconds: float = DEFAULT_TRANSIENT_SPEECH_TTL_S) -> SpeechRequest:
        """Rendre la meme demande, avec une echeance si elle est transitoire.

        Sans echeance, une progression reste prononcable indefiniment : rien ne
        la perime hors revision d'intention ou trou de flux, et Jarvis peut
        annoncer dix minutes plus tard une etape depassee depuis longtemps
        (Decision 31). Une echeance deja fixee est respectee telle quelle : le
        cerveau sait mieux que la regle par defaut quand sa phrase cesse d'etre
        vraie. Une parole non transitoire est rendue inchangee.
        """

        if not self.is_transient or self.expires_at is not None:
            return self
        if seconds <= 0:
            raise ValueError("transient speech ttl must be strictly positive")
        return replace(self, expires_at=self.created_at + timedelta(seconds=seconds))

    def supersedes(self, other: SpeechRequest) -> bool:
        """Vrai si `self` rend `other` obsolete dans la meme conversation.

        Relation dirigee : une demande partageant la meme cle de supersession
        remplace la precedente. A defaut de cle, un resultat final ou une erreur
        rend caduque une progression du meme travail (spec section 6).
        """

        if self.conversation_id != other.conversation_id or self.id == other.id:
            return False
        if self.supersedes_key is not None and self.supersedes_key == other.supersedes_key:
            return self.created_at >= other.created_at
        if self.work_id is None or self.work_id != other.work_id:
            return False
        return self.kind in (SpeechKind.RESULT, SpeechKind.ERROR) and other.kind is SpeechKind.PROGRESS

    def to_payload(self) -> dict[str, Any]:
        return {
            "speech_id": self.id,
            "conversation_id": self.conversation_id,
            "text": self.text,
            "kind": self.kind.value,
            "priority": self.priority.label,
            "correlation_id": self.correlation_id,
            "work_id": self.work_id,
            "supersedes_key": self.supersedes_key,
            "interruptible": self.interruptible,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "provenance": self.provenance.value,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SpeechRequest:
        expires_at = payload.get("expires_at")
        created_at = payload.get("created_at")
        return cls(
            conversation_id=str(payload.get("conversation_id") or ""),
            text=str(payload.get("text") or ""),
            kind=SpeechKind(payload.get("kind", SpeechKind.PROGRESS)),
            priority=SpeechPriority.from_label(str(payload.get("priority", SpeechPriority.NORMAL.label))),
            id=str(payload.get("speech_id") or new_id()),
            correlation_id=str(payload.get("correlation_id") or new_id()),
            work_id=payload.get("work_id"),
            supersedes_key=payload.get("supersedes_key"),
            interruptible=bool(payload.get("interruptible", True)),
            expires_at=_parse_aware(expires_at) if expires_at else None,
            provenance=SpeechProvenance(payload.get("provenance", SpeechProvenance.BRAIN)),
            created_at=_parse_aware(created_at) if created_at else utc_now(),
        )


@dataclass(frozen=True, slots=True)
class PlaybackCursor:
    """Quantite de parole reellement entendue par l'utilisateur.

    Necessaire a la troncature de l'historique fournisseur lors d'un barge-in
    (spec section 12). Les identifiants fournisseur restent opaques pour Core :
    seule la surface Realtime les interprete.
    """

    speech_id: str
    played_ms: int = 0
    provider_response_id: str | None = None
    provider_item_id: str | None = None

    def __post_init__(self) -> None:
        if not self.speech_id:
            raise ValueError("speech_id is required")
        if self.played_ms < 0:
            raise ValueError("played_ms must be positive or zero")


@dataclass(frozen=True, slots=True)
class BrainTurnInput:
    """Tour utilisateur complet faisant autorite, soumis au cerveau.

    Seul un transcript complet declenche du travail irreversible (Decision 07).
    """

    conversation_id: str
    text: str
    correlation_id: str = field(default_factory=new_id)
    source: BrainTurnSource = BrainTurnSource.REALTIME
    #: Ce que la surface a cru du tour au moment de le router (Decision 44).
    #: `ADDRESSED` reste le cas normal ; `UNCERTAIN` dit que la surface n'a pas
    #: su si la phrase lui etait adressee et laisse l'intention au cerveau.
    #: `AMBIENT` n'est jamais route : le refuser ici rend la borne mecanique.
    addressing: AddressingDecision = AddressingDecision.ADDRESSED
    provider_item_id: str | None = None
    interrupted_speech_id: str | None = None
    received_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        if not self.text.strip():
            raise ValueError("turn text is required")
        if not self.correlation_id:
            raise ValueError("correlation_id is required")
        if self.addressing is AddressingDecision.AMBIENT:
            raise ValueError("an ambient turn is never submitted to the brain")
        _aware(self.received_at)

    @property
    def dedup_key(self) -> str:
        """Cle de deduplication obligatoire (Decision 24)."""

        return self.correlation_id

    @property
    def secondary_dedup_key(self) -> str | None:
        """Cle secondaire optionnelle, absente des surfaces sans identifiant fournisseur."""

        return self.provider_item_id or None

    def to_payload(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "content": self.text,
            "correlation_id": self.correlation_id,
            "source": self.source.value,
            "addressing": self.addressing.value,
            "provider_item_id": self.provider_item_id,
            "interrupted_speech_id": self.interrupted_speech_id,
            "received_at": self.received_at.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> BrainTurnInput:
        received_at = payload.get("received_at")
        return cls(
            conversation_id=str(payload.get("conversation_id") or ""),
            text=str(payload.get("content") or ""),
            correlation_id=str(payload.get("correlation_id") or new_id()),
            source=BrainTurnSource(payload.get("source", BrainTurnSource.REALTIME)),
            addressing=AddressingDecision(payload.get("addressing") or AddressingDecision.ADDRESSED),
            provider_item_id=payload.get("provider_item_id"),
            interrupted_speech_id=payload.get("interrupted_speech_id"),
            received_at=_parse_aware(received_at) if received_at else utc_now(),
        )


@dataclass(frozen=True, slots=True)
class BrainTurnAcceptance:
    """Accuse de reception rendu immediatement par l'ingress cerveau (spec section 4).

    Retourne avant toute execution du backend fort : la soumission ne bloque
    jamais sur le modele.
    """

    turn_id: str
    conversation_id: str
    correlation_id: str
    revision: int = 0
    duplicate: bool = False
    provider_item_id: str | None = None
    interrupted_speech_id: str | None = None
    accepted_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.turn_id or not self.conversation_id or not self.correlation_id:
            raise ValueError("turn_id, conversation_id and correlation_id are required")
        if self.revision < 0:
            raise ValueError("revision must be positive or zero")
        _aware(self.accepted_at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "conversation_id": self.conversation_id,
            "correlation_id": self.correlation_id,
            "revision": self.revision,
            "duplicate": self.duplicate,
            "provider_item_id": self.provider_item_id,
            "interrupted_speech_id": self.interrupted_speech_id,
        }


@dataclass(frozen=True, slots=True)
class BrainWorkingState:
    """Etat de travail public et durable d'une conversation.

    Aucun raisonnement cache (Decision 12) : uniquement ce qui peut etre
    restitue a l'utilisateur ou rejoue apres redemarrage. L'orchestrateur est
    seul proprietaire des transitions ; chaque revision produit une instance.
    """

    conversation_id: str
    revision: int = 0
    current_user_intent: str = ""
    conversation_goal: str = ""
    active_work_ids: tuple[str, ...] = ()
    known_public_facts: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    completed_work_ids: tuple[str, ...] = ()
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        if self.revision < 0:
            raise ValueError("revision must be positive or zero")
        _aware(self.updated_at)

    def to_public_payload(self) -> dict[str, Any]:
        """Projection sure publiee dans `brain.state.updated`.

        Les listes longues sont reduites a des compteurs : l'evenement sert au
        diagnostic et a la rehydratation d'UI, pas au transport de contenu.
        """

        return {
            "conversation_id": self.conversation_id,
            "revision": self.revision,
            "current_user_intent": self.current_user_intent,
            "active_work_ids": list(self.active_work_ids),
            "unresolved_question_count": len(self.unresolved_questions),
            "completed_work_count": len(self.completed_work_ids),
        }

    def to_rehydration_payload(self) -> dict[str, Any]:
        """Projection complete servant a reprendre une conversation (Decision 33).

        Difference avec `to_public_payload()` : celle-ci circule sur le bus a
        chaque revision, donc elle reduit les listes a des compteurs. Ici on
        rend le contenu, parce que c'est precisement ce que l'utilisateur n'a
        pas entendu — un `Jarvis Mute` ne reveille pas la surface pour dire un
        resultat, mais ce resultat doit rester lisible a la reactivation
        suivante.

        Toujours aucun raisonnement cache (Decision 12) : ces champs sont ceux
        de l'etat public, sans exception.
        """

        return {
            "conversation_id": self.conversation_id,
            "revision": self.revision,
            "current_user_intent": self.current_user_intent,
            "conversation_goal": self.conversation_goal,
            "active_work_ids": list(self.active_work_ids),
            "known_public_facts": list(self.known_public_facts),
            "unresolved_questions": list(self.unresolved_questions),
            "completed_work_ids": list(self.completed_work_ids),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class BrainIntentRevision:
    """Annonce publique d'un changement d'intention (`brain.intent.revised`).

    Dit aux consommateurs ce qu'il advient du travail en cours au moment ou
    l'intention change. Les trois listes partitionnent le travail qui etait
    actif juste avant la revision, et cette partition **est** la regle de
    retention du projet :

    - `retained_work_ids` : le travail continue et ce qu'il annonce reste vrai.
      C'est le cas par defaut, y compris quand l'utilisateur coupe la parole a
      Jarvis : interrompre n'est pas annuler (spec section 12, point 9).
    - `superseded_work_ids` : le travail continue, mais la parole deja en file
      a son sujet ne decrit plus l'intention courante et ne doit pas etre
      prononcee (Decision 31 : on perime, on ne rejoue pas).
    - `cancelled_work_ids` : le travail a ete arrete sur decision explicite du
      cerveau, seule autorite habilitee a le faire.

    Les listes sont donc disjointes deux a deux : un meme travail ne peut pas
    etre a la fois garde et retire.
    """

    conversation_id: str
    revision: int
    previous_revision: int = 0
    superseded_work_ids: tuple[str, ...] = ()
    cancelled_work_ids: tuple[str, ...] = ()
    retained_work_ids: tuple[str, ...] = ()
    revised_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        if self.previous_revision < 0:
            raise ValueError("previous_revision must be positive or zero")
        if self.revision <= self.previous_revision:
            # Une revision qui n'avance pas ne se distingue pas de l'etat
            # precedent : le consommateur ne pourrait plus detecter un trou.
            raise ValueError("revision must be greater than previous_revision")
        buckets = (self.superseded_work_ids, self.cancelled_work_ids, self.retained_work_ids)
        seen: set[str] = set()
        for bucket in buckets:
            for work_id in bucket:
                if work_id in seen:
                    raise ValueError(f"work id {work_id!r} appears in two revision buckets")
                seen.add(work_id)
        _aware(self.revised_at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "revision": self.revision,
            "previous_revision": self.previous_revision,
            "superseded_work_ids": list(self.superseded_work_ids),
            "cancelled_work_ids": list(self.cancelled_work_ids),
            "retained_work_ids": list(self.retained_work_ids),
        }


@dataclass(frozen=True, slots=True)
class BrainEvent:
    """Signal incremental emis par un backend cerveau vers l'orchestrateur.

    Le backend ne publie jamais directement sur `CoreEventBus` (spec section 3) ;
    il alimente un `BrainEventSink` que l'orchestrateur possede.
    """

    kind: BrainEventKind
    conversation_id: str
    correlation_id: str
    work_id: str | None = None
    public_summary: str = ""
    speech: SpeechRequest | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.conversation_id or not self.correlation_id:
            raise ValueError("conversation_id and correlation_id are required")
        _aware(self.created_at)
        if self.kind is BrainEventKind.SPEECH:
            if self.speech is None:
                raise ValueError("SPEECH events must carry a SpeechRequest")
            if self.speech.conversation_id != self.conversation_id:
                raise ValueError("speech conversation_id must match the event")
        elif self.speech is not None:
            raise ValueError("only SPEECH events may carry a SpeechRequest")
        if self.kind is BrainEventKind.FAILED and not (self.error or "").strip():
            raise ValueError("FAILED events must carry an error")
        if self.kind in (BrainEventKind.SUPERSEDED, BrainEventKind.CANCELLED) and not (self.work_id or "").strip():
            # Retirer du travail se fait par designation, jamais en bloc : sans
            # `work_id`, l'evenement demanderait implicitement « annule tout »,
            # ce que la retention par defaut interdit.
            raise ValueError(f"{self.kind.value} events must name a work_id")


@dataclass(frozen=True, slots=True)
class BrainTurnResult:
    """Issue d'un tour cerveau, rendue par le backend a l'orchestrateur.

    Ne porte pas de revision : les transitions d'etat appartiennent a
    l'orchestrateur, pas au fournisseur.
    """

    correlation_id: str
    status: BrainRunStatus = BrainRunStatus.COMPLETED
    public_summary: str = ""
    error: str | None = None
    completed_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.correlation_id:
            raise ValueError("correlation_id is required")
        _aware(self.completed_at)
        if self.status is BrainRunStatus.FAILED and not (self.error or "").strip():
            raise ValueError("failed brain turns must carry an error")
        if self.status is BrainRunStatus.COMPLETED and self.error:
            raise ValueError("completed brain turns must not carry an error")


def declared_wire_form(value: Any) -> dict[str, Any] | None:
    """Rendre la forme de fil qu'un objet declare lui-meme, sinon None.

    Regle generale du domaine : un type peut publier sa propre representation
    de transport en exposant `to_payload()`. Sans cette regle, la projection
    generique et la forme documentee divergent silencieusement -- par exemple
    `SpeechRequest`, dont le champ interne s'appelle `id` et dont la priorite
    est un `IntEnum`, alors que `docs/05-event-contracts.md` impose
    `speech_id` et une priorite textuelle.

    Une classe (et non une instance) n'a pas de forme de fil : le test
    `isinstance(value, type)` evite de confondre le type et sa valeur.
    """

    if isinstance(value, type):
        return None
    method = getattr(value, "to_payload", None)
    if not callable(method):
        return None
    payload = method()
    if not isinstance(payload, dict):
        raise TypeError(f"{type(value).__name__}.to_payload() must return a dict")
    return payload


def jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    # La forme declaree prime sur la projection generique, et elle est testee
    # avant `__dataclass_fields__` : les trois types concernes sont justement
    # des dataclasses, que la branche suivante capterait sinon en premier.
    declared = declared_wire_form(value)
    if declared is not None:
        return jsonable(declared)
    if hasattr(value, "__dataclass_fields__"):
        # Parcours champ par champ plutot que `asdict()` : `asdict()` aplatit
        # les dataclasses imbriquees avant que `jsonable` ne les voie, ce qui
        # ferait perdre la forme declaree d'un objet imbrique.
        return {f.name: jsonable(getattr(value, f.name)) for f in fields(value)}
    return value
