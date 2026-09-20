from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import time
import uuid

from jarvis.core.conversation_event_emitter import PRODUCER_BRAIN_SERVICE, journal_ref, journal_trace, safe_error_class
from jarvis.core.latency import FIRST_BRAIN_AUDIO as LATENCY_FIRST_BRAIN_AUDIO, LatencyTracker
from jarvis.core.v2_services import SystemClock
from jarvis.domain.v2 import (
    SPEECH_DELIVERY_PARTIAL,
    TRANSIENT_SPEECH_KINDS,
    PlaybackCursor,
    ProtocolEnvelope,
    SpeechKind,
    SpeechProvenance,
    SpeechRequest,
)
from jarvis.domain.reflex_policy import ReflexAction, ReflexDecision, decide_reflex
from jarvis.domain.voice_frontend import VoiceReflexRequest
from jarvis.domain.speech_presentation import MAX_SPEECH_CHUNK_TEXT, SpeechCandidateStatus, SpeechChunk, SpeechDependency, SpeechSource, SpeechTextSpan, semantic_text_spans
from jarvis.domain.conversation_events import ConversationEventType, EventShape, event_shape
from jarvis.ports.v2 import Clock, ConversationEventRecorder, RealtimeOutputControl, supports_reflex
from jarvis.runtime.conversation_event_forwarder import PRODUCER_SPEECH_SCHEDULER, optional_id, public_text
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.output_admission import OutputAdmission, OutputAdmissionState
from jarvis.runtime.conversation_presentation import ConversationCandidate
from jarvis.domain.voice_frontend import VoiceConversationRequest

# Types d'événements Core consommés ici. Ils sont repris de `brain_service`
# sous forme de littéraux : le runtime ne doit pas importer `jarvis.core`
# pour connaître un nom de canal, et le contrat de transport est
# `docs/handoff-realtime-brain/docs/05-event-contracts.md`, pas un module.
BRAIN_SPEECH_REQUESTED = "brain.speech.requested"
BRAIN_TURN_ACCEPTED = "brain.turn.accepted"
BRAIN_STATE_UPDATED = "brain.state.updated"
BRAIN_INTENT_REVISED = "brain.intent.revised"
BRAIN_WORK_STARTED = "brain.work.started"
BRAIN_WORK_COMPLETED = "brain.work.completed"
BRAIN_WORK_FAILED = "brain.work.failed"
BRAIN_EVENT_PREFIX = "brain."

# Télémétrie de livraison (docs/05, section « Voice delivery telemetry »).
# Journal local uniquement : Core n'a pas besoin de savoir ce que le
# haut-parleur a fait, et la Décision 27 dit que `RuntimeJournal` est le
# support d'observabilité de ce dépôt.
SPEECH_QUEUED = "voice.speech.queued"
SPEECH_DISPATCHED = "voice.speech.dispatched"
SPEECH_STARTED = "voice.speech.started"
SPEECH_COMPLETED = "voice.speech.completed"
SPEECH_INTERRUPTED = "voice.speech.interrupted"
SPEECH_EXPIRED = "voice.speech.expired"
SPEECH_SUPERSEDED = "voice.speech.superseded"
SPEECH_IGNORED = "voice.speech.ignored"
SPEECH_TURN_ABANDONED = "voice.speech.turn_abandoned"
SPEECH_DECIDED = "voice.speech.presentation_decided"
SPEECH_ERROR_WITHHELD = "voice.speech.error_withheld"
# Solde explicite d'une parole durable qui meurt sans avoir été tentée. Une
# réponse ne disparaît jamais en silence : ou elle est dite, ou cette ligne dit
# qui l'a retirée et ce qu'elle contenait.
SPEECH_ABANDONED = "voice.speech.abandoned"

# Accusé de réception de la surface (mode continu) : proposé par le bridge après
# un tour adressé, prononcé seulement si le cerveau n'a encore rien dit.
REFLEX_STARTED = "voice.reflex.started"
REFLEX_SKIPPED = "voice.reflex.skipped"
REFLEX_DECIDED = "voice.reflex.decided"

# Mesure 3 des six de `docs/04-testing-and-quality.md` : de la demande de parole
# du cerveau au premier bloc audio réellement rendu. Elle se joint par
# `speech_id`. Les deux bornes sont prises dans ce processus — la réception de
# la demande, pas son émission par Core — donc le transport Core → Voice n'y est
# pas compté, et une horloge monotone reste valable.
LATENCY_FIRST_BRAIN_AUDIO_KIND = "voice.latency.first_brain_audio"

# Diagnostics propres à l'ordonnanceur : ils ne décrivent pas le sort d'une
# demande de parole mais celui du flux qui les transporte.
STREAM_CLOSED = "voice.speech.stream_closed"
STREAM_FAILED = "voice.speech.stream_failed"
REVISION_GAP = "voice.speech.revision_gap"
OUTPUT_STALLED = "voice.speech.output_stalled"
PERSIST_FAILED = "voice.speech.persist_failed"
SPEAK_FAILED = "voice.speech.speak_failed"
PRODUCER_FAILED = "voice.conversation_events.producer_failed"

# Conversation Events (handoff conversation-observability, Slice 03b). Mouth
# events are recorded where the matching journal line is written, and that line
# carries `conversation_event_id` (`docs/conversation-events.md`). Memory is
# bounded like `_seen_speech_ids`.
_T = ConversationEventType
MAX_MOUTH_EVENT_MEMORY = 4096

# Une progression ou un accusé sont vrais à l'instant où le cerveau les rédige
# et faux dès que l'intention change ou qu'un trou s'ouvre dans le flux. Un
# résultat, une erreur ou une question restent, eux, de la vérité que seul le
# cerveau peut retirer (Décisions 14 et 16) : la surface ne les jette jamais.
#
# La liste vient du domaine : Core l'utilise pour dater la péremption, cet
# ordonnanceur pour jeter ce qui n'est plus vrai. Deux copies divergeraient.
TRANSIENT_KINDS = TRANSIENT_SPEECH_KINDS


@dataclass(slots=True)
class _ActiveSpeech:
    """Sortie vocale du cerveau en cours, du `speak()` au `response.done`.

    Possédée par la boucle de livraison ; renseignée par les notifications que
    le bridge lui transmet. Toutes ces écritures ont lieu dans la même boucle
    asyncio, sans point de suspension entre lecture et écriture : aucun verrou
    n'est pris, et cette invariante doit être revue si un jour deux tâches
    pilotaient la même session.
    """

    request: SpeechRequest | ConversationCandidate
    output_id: str
    done: asyncio.Event = field(default_factory=asyncio.Event)
    status: str = "unknown"
    # Coupée par la parole de l'utilisateur, et ce qui en a été entendu. Le
    # statut du fournisseur ne suffit pas : `cancelled` peut aussi venir d'un
    # échec, et lui seul ne dit pas combien de millisecondes ont été jouées.
    interrupted: bool = False
    played_ms: int = 0
    admission: OutputAdmission | None = None


@dataclass(slots=True)
class _Candidate:
    request: SpeechRequest
    status: SpeechCandidateStatus
    reason: str
    chunk: SpeechChunk


@dataclass(slots=True)
class _Reflex:
    """Accusé de réception en attente : dû à `due`, caduc après `expires`.

    Échéances en temps de boucle asyncio (`loop.time()`) : ce sont des délais
    à attendre, pas des dates à comparer à celles du cerveau.
    """

    transcript: str
    correlation_id: str
    avoid: tuple[str, ...]
    due: float
    expires: float
    requested: float
    next_check: float
    output_id: str | None = None
    admission: OutputAdmission | None = None


class SpeechScheduler:
    """Décide ce que la surface vocale dit maintenant, et le fait dire une fois.

    Propriété
    ---------
    - L'ordonnanceur possède la file de parole du cerveau et la sortie vocale
      qu'il a déclenchée. Il ne possède ni le micro (au bridge), ni le travail
      du cerveau (à Core), ni le texte (au cerveau : il n'en réécrit jamais un
      mot, Décision 13).
    - Sa durée de vie est celle du **transport vocal ACTIF**, pas celle du
      travail. `PersistentVoiceRuntime` le démarre juste avant le bridge et
      l'arrête au mute. Le travail lui survit dans Core (Décision 11), et son
      résultat n'est donc pas prononcé si l'utilisateur a coupé la voix entre
      temps (Décision 33) : il périme ici, et reste lisible dans Core.

    Concurrence
    -----------
    Deux tâches, une seule boucle asyncio.

    - `_consume_core_events` lit `/v1/events`, filtre, met en file, et se
      réabonne quand le flux se tait. Un abonné évincé pour file saturée ne
      reçoit aucune erreur (Décision 25) : la fermeture silencieuse est donc
      traitée comme un incident, pas comme une fin normale.
    - `_deliver_pending` est **le seul** appelant de `speak()`. C'est cette
      unicité qui garantit une seule sortie cerveau active à la fois : le
      fournisseur refuse un second `response.create` pendant une génération, et
      `speak()` n'a aucune protection propre. La boucle attend en plus que la
      surface soit silencieuse — y compris quand ce qui parle est un réflexe de
      surface, qui occupe le fournisseur tout autant.

    Ce que cet ordonnanceur ne fait pas
    -----------------------------------
    Il ne déclenche pas l'interruption : c'est le bridge qui possède le micro,
    donc lui qui voit l'utilisateur reprendre la parole et qui coupe la lecture
    (`RealtimeConversationBridge._barge_in`). L'ordonnanceur en est *notifié*
    par `note_interruption()`, parce qu'il est seul à savoir quelle
    `SpeechRequest` la sortie restituait. Une demande qui en périme une autre
    n'interrompt toujours rien : elle attend la fin de la phrase en cours.
    """

    # Marge au-delà de laquelle une sortie qu'on croyait en cours est suspecte.
    # Ne sert qu'à re-interroger l'adaptateur : c'est sa comptabilité qui
    # tranche, pas ce délai.
    OUTPUT_TIMEOUT_S = 30.0

    # Une reconnexion immédiate en boucle sur un Core absent ferait tourner le
    # processus à vide ; deux secondes restent invisibles à l'oreille.
    RECONNECT_DELAY_S = 2.0

    # Échéance de repli appliquée à une parole transitoire qui arrive sans
    # `expires_at`. Volontairement plus généreuse que celle de Core
    # (`DEFAULT_TRANSIENT_SPEECH_TTL_S`, 45 s) : quand les deux s'appliquent,
    # c'est celle du cerveau qui doit gagner. Cette valeur-ci n'est qu'un
    # filet, pour le jour où un backend oublierait de dater sa péremption.
    TRANSIENT_TTL_S = 60.0

    # Au-delà de son échéance, un accusé de réception arrive trop tard pour
    # être naturel : mieux vaut se taire jusqu'à la réponse.
    REFLEX_GRACE_S = 2.5

    # L'utilisateur parle : la parole attend qu'il ait fini, mais pas
    # indéfiniment — un VAD bloqué sur un bruit continu ne doit pas bâillonner
    # JARVIS.
    USER_SPEECH_HOLD_MAX_S = 8.0

    def __init__(
        self,
        *,
        core,
        conversation_id: str,
        session: RealtimeOutputControl,
        journal: RuntimeJournal | None = None,
        clock: Clock | None = None,
        on_brain_activity: Callable[[], object] | None = None,
        output_timeout_s: float | None = None,
        reconnect_delay_s: float | None = None,
        transient_ttl_s: float | None = None,
        reflex_delay_s: float = 0.0,
        reflex_require_work: bool = False,
        user_speech_hold_s: float | None = None,
        conversation_events: ConversationEventRecorder | None = None,
    ) -> None:
        self.core = core
        # Enregistreur synchrone et borné (`ConversationEventForwarder`) : jamais
        # d'attente ni d'exception sur le chemin de la parole. None : rien.
        self.conversation_events = conversation_events
        # Demandes reçues de Core (`brain.speech.requested`, que Core enregistre
        # toujours) : seules elles ont un parent Conversation Event certain.
        self._core_speech_ids: OrderedDict[str, None] = OrderedDict()
        # Paroles dont `mouth.speech.started` est enregistré, et son heure : la
        # fermeture du span en reprend le début.
        self._mouth_started: OrderedDict[str, datetime] = OrderedDict()
        self.conversation_id = conversation_id
        self.session = session
        self.journal = journal
        self.clock = clock or SystemClock()
        monotonic = getattr(self.clock, "monotonic", None)
        self._monotonic = monotonic if callable(monotonic) else time.monotonic
        self.on_brain_activity = on_brain_activity
        self.output_timeout_s = self.OUTPUT_TIMEOUT_S if output_timeout_s is None else output_timeout_s
        self.reconnect_delay_s = self.RECONNECT_DELAY_S if reconnect_delay_s is None else reconnect_delay_s
        self.transient_ttl_s = self.TRANSIENT_TTL_S if transient_ttl_s is None else transient_ttl_s

        self._pending: list[SpeechRequest] = []
        self._deferred: OrderedDict[str, SpeechRequest] = OrderedDict()
        self._candidates: OrderedDict[str, _Candidate] = OrderedDict()
        self._chain_next: OrderedDict[str, int] = OrderedDict()
        self._blocked_chains: set[str] = set()
        # Corrélations dont l'utilisateur a repris la parole pendant que le
        # cerveau réfléchissait : leur réponse n'a plus lieu d'être. Bornée,
        # parce qu'une demande de parole émise juste avant l'abandon peut
        # traverser `/v1/events` après lui, et serait sinon prononcée par-dessus
        # la nouvelle question.
        self._abandoned_correlations: OrderedDict[str, None] = OrderedDict()
        self._attempted_ids: set[str] = set()
        self._queued_at: dict[str, float] = {}
        self._current_source: SpeechSource | None = None
        self._source_complete = False
        self._intent_watermark = -1
        self._invalidated_dependencies: set[SpeechDependency] = set()
        self._presentation_admissions: dict[str, OutputAdmission] = {}
        self._presentation_cancels: set[asyncio.Task] = set()
        self._presentation_cancelled: set[str] = set()
        self._presentation_expiries: dict[str, asyncio.TimerHandle] = {}
        self._source_refresh: asyncio.Task | None = None
        self._source_queries: set[asyncio.Task] = set()
        self._stopping = False
        self._source_generation = 0
        self._stream_connected = False
        self._wakeup = asyncio.Event()
        self._active: _ActiveSpeech | None = None
        # Sorties fournisseur commencées et pas encore terminées, quelle qu'en
        # soit l'origine. Tant qu'il en reste une, parler créerait une seconde
        # réponse concurrente et le fournisseur répondrait
        # `conversation_already_has_active_response`.
        self._live_outputs: set[str] = set()
        self._idle = asyncio.Event()
        self._idle.set()
        self._last_revision: int | None = None
        # Demandes déjà vues, par `speech_id`. Core n'émet normalement chaque
        # parole qu'une fois, mais une reconnexion ou un doublon côté Core ne
        # doit pas faire répéter une phrase à Jarvis. Borné par le nombre de
        # paroles d'une session vocale, et vidé à l'arrêt.
        self._seen_speech_ids: set[str] = set()
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False
        # Chronomètre de la mesure 3. Il vit ici parce que l'ordonnanceur est le
        # seul à dater l'arrivée d'une demande de parole ; le bridge, lui, est le
        # seul à voir l'audio, et le lui notifie (`note_output_event`).
        self._latency = LatencyTracker(journal)
        # Accusé de réception : délai laissé au cerveau avant que la surface
        # ne dise qu'elle a compris. 0 = jamais.
        self.reflex_delay_s = max(0.0, float(reflex_delay_s))
        # Retour arrière seulement : exiger un `brain.work.started` corrélé
        # avant d'autoriser le préambule. Voir `decide_reflex`.
        self.reflex_require_work = bool(reflex_require_work)
        self.user_speech_hold_s = self.USER_SPEECH_HOLD_MAX_S if user_speech_hold_s is None else user_speech_hold_s
        self._reflex: _Reflex | None = None
        self._live_reflex: _Reflex | None = None
        self._reflex_work: OrderedDict[str, tuple[str, bool]] = OrderedDict()
        self._reflex_terminal: OrderedDict[str, bool] = OrderedDict()
        self._reflex_decisions: OrderedDict[str, ReflexDecision] = OrderedDict()
        self._reflex_used: set[str] = set()
        self._reflex_requested: set[str] = set()
        self._reflex_admissions: dict[str, OutputAdmission] = {}
        self._reflex_cancels: set[asyncio.Task] = set()
        self._reflex_cancelled: set[str] = set()
        self._reflex_expiries: dict[str, asyncio.TimerHandle] = {}
        # Posé par le runtime quand le bridge existe : une sortie dont le
        # fournisseur a fini la génération peut encore jouer ici pendant de
        # longues secondes. Sans lui, une phrase de plus de `output_timeout_s`
        # passait pour bloquée et la suivante partait par-dessus.
        self.output_alive: Callable[[str], bool] | None = None
        self._user_speaking = False
        self._user_quiet = asyncio.Event()
        self._user_quiet.set()
        self._active_continuation_until: float | None = None

    # -- cycle de vie -------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def immediate_continuation_pending(self) -> bool:
        """A bounded, already-admitted utterance is being delivered now."""
        return self.immediate_continuation_until is not None

    @property
    def immediate_continuation_until(self) -> float | None:
        """Loop-clock deadline; durable/background work never creates one."""
        now = asyncio.get_running_loop().time()
        deadlines = []
        if self._active_continuation_until is not None:
            deadlines.append(self._active_continuation_until)
        for reflex in (self._live_reflex, self._reflex):
            if reflex is not None:
                deadlines.append(reflex.expires)
        future = [deadline for deadline in deadlines if deadline > now]
        return max(future) if future else None

    async def start(self) -> None:
        """Démarrer l'abonnement et la boucle de livraison."""

        if self._running:
            return
        if self._stopping:
            raise RuntimeError("A stopped scheduler requires a new frontend incarnation")
        self._running = True
        self._source_unknown("activation")
        self._tasks = [
            asyncio.create_task(self._consume_core_events(), name="jarvis-speech-events"),
            asyncio.create_task(self._deliver_pending(), name="jarvis-speech-delivery"),
        ]

    async def stop(self) -> None:
        """Arrêter l'ordonnanceur et périmer ce qui n'a pas été dit.

        Appelé quand la voix repasse au fond. La file n'est pas conservée pour
        « plus tard » : réveiller la surface pour dire un résultat que
        l'utilisateur a coupé irait contre sa propre commande (Décision 33).
        """

        self._running = False
        self._stopping = True
        self._source_complete = False
        self._stream_connected = False
        self._source_generation += 1
        self._invalidate_reflex("voice_background")
        if self._active is not None:
            self._invalidate_presentation(self._active, "voice_background")
        for handle in self._presentation_expiries.values():
            handle.cancel()
        self._presentation_expiries.clear()
        for query in tuple(self._source_queries):
            query.cancel()
        for handle in self._reflex_expiries.values():
            handle.cancel()
        self._reflex_expiries.clear()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            if task is not asyncio.current_task():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._source_queries:
            await asyncio.gather(*tuple(self._source_queries), return_exceptions=True)
        if self._reflex_cancels:
            await asyncio.gather(*tuple(self._reflex_cancels), return_exceptions=True)
        if self._presentation_cancels:
            await asyncio.gather(*tuple(self._presentation_cancels), return_exceptions=True)
        self._expire_all(reason="voice_background")
        for request in tuple(self._deferred.values()):
            self._decision(request, SpeechCandidateStatus.EXPIRED, "voice_background")
        self._deferred.clear()
        self._active = None
        self._reflex = None
        self._live_reflex = None
        self._reflex_work.clear()
        self._reflex_terminal.clear()
        self._reflex_decisions.clear()
        self._live_outputs.clear()
        self._idle.set()
        self.note_user_speech(False)

    # -- accusé de réception et tour de parole ---------------------------------

    def request_reflex(self, transcript: str, *, correlation_id: str, avoid: tuple[str, ...] = ()) -> None:
        """Proposer un accusé de réception pour le tour qui vient d'être soumis.

        Il n'est prononcé qu'après `reflex_delay_s`, et seulement si le cerveau
        n'a encore rien demandé à dire : une réponse rapide le rend inutile, et
        la répétition « Entendu. » à chaque phrase était précisément ce qui
        rendait la conversation mécanique. Le plus récent remplace le
        précédent.

        Le silence du cerveau suffit : aucune déclaration de travail de fond
        n'est exigée (`decide_reflex`), sans quoi les tours auxquels le cerveau
        répond lui-même — l'immense majorité — resteraient sans accusé.
        """

        now = asyncio.get_running_loop().time()
        VoiceReflexRequest(transcript, avoid)  # Reuse the canonical bounds before retaining user data.
        if not isinstance(correlation_id, str) or not correlation_id or len(correlation_id) > 256 or correlation_id.strip() != correlation_id or not correlation_id.isprintable():
            raise ValueError("Reflex correlation must be a bounded printable ID")
        if correlation_id in self._reflex_requested:
            return  # Includes completed/expired candidates: never cancel or rearm a duplicate.
        if len(self._reflex_requested) >= 4096:
            return  # Session retention exhausted: silence, without forgetting dedup evidence.
        self._reflex_requested.add(correlation_id)
        self._invalidate_reflex("new_turn")
        due = now + self.reflex_delay_s
        candidate = _Reflex(
            transcript=transcript,
            correlation_id=correlation_id,
            avoid=tuple(avoid),
            due=due,
            expires=due + self.REFLEX_GRACE_S,
            requested=now,
            next_check=due,
        )
        decision = self._decide_reflex(candidate)
        self._record_reflex_decision(candidate, decision, "request")
        if decision.reason not in ("work_unconfirmed", "answer_may_arrive_quickly",
                                   "confirmed_work_wait", "brain_silent_wait"):
            return
        self._reflex = candidate
        self._wakeup.set()

    def _decide_reflex(self, reflex: _Reflex) -> ReflexDecision:
        now = asyncio.get_running_loop().time()
        return decide_reflex(text=reflex.transcript,
            enabled=self._running and self.reflex_delay_s > 0 and supports_reflex(self.session)
                    and callable(getattr(self.session, "invalidate_reflex", None)) and len(self._reflex_used) < 4096,
            admitted=True, user_speaking=self._user_speaking,
            useful_ready=bool(self._pending) or self._active is not None,
            work_confirmed=any(correlation == reflex.correlation_id and active for correlation, active in self._reflex_work.values()),
            work_terminal=reflex.correlation_id in self._reflex_terminal,
            noticeable_wait=now >= reflex.due, already_used=reflex.correlation_id in self._reflex_used,
            stale=now > reflex.expires, require_work=self.reflex_require_work)

    def _record_reflex_decision(self, reflex: _Reflex, decision: ReflexDecision, phase: str) -> None:
        self._reflex_decisions[reflex.correlation_id] = decision
        self._reflex_decisions.move_to_end(reflex.correlation_id)
        while len(self._reflex_decisions) > 128:
            self._reflex_decisions.popitem(last=False)
        self._trace(REFLEX_DECIDED, "Reflex gate decision", data={"conversation_id": self.conversation_id,
            "session_id": str(getattr(self.session, "session_id", "")) or None,
            "correlation_id": reflex.correlation_id, "action": decision.action.value, "reason": decision.reason,
            "phase": phase, "elapsed_ms": round((asyncio.get_running_loop().time() - reflex.requested) * 1000, 3)})

    def output_admission(self, output_id: str) -> OutputAdmission | None:
        return self._presentation_admissions.get(output_id) or self._reflex_admissions.get(output_id)

    def _invalidate_reflex(self, reason: str, *, correlation_id: str | None = None) -> None:
        seen: set[int] = set()
        for reflex in (self._reflex, self._live_reflex):
            if reflex is None or (correlation_id is not None and reflex.correlation_id != correlation_id):
                continue
            if id(reflex) in seen or (reflex.output_id is not None and reflex.output_id in self._reflex_cancelled):
                continue
            seen.add(id(reflex))
            if reflex.admission is not None and not reflex.admission.invalidate():
                continue  # A native write already began; this is not proven unplayed.
            self._record_reflex_decision(reflex, ReflexDecision(ReflexAction.WAIT, reason), "invalidate")
            self._skip_reflex(reflex, "brain_answered" if reason == "useful_content_ready" else reason)
            if reflex is self._reflex:
                self._reflex = None
            if reflex.output_id is not None:
                self._reflex_cancelled.add(reflex.output_id)
                cancel = getattr(self.session, "invalidate_reflex", None)
                if callable(cancel):
                    task = asyncio.create_task(self._cancel_reflex(cancel, reflex.output_id))
                    self._reflex_cancels.add(task)
                    task.add_done_callback(self._reflex_cancels.discard)

    async def _cancel_reflex(self, cancel, output_id: str) -> None:
        try:
            await asyncio.wait_for(cancel(output_id), self.output_timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._trace(SPEAK_FAILED, "Reflex cancellation failed", level="warning",
                        data={"conversation_id": self.conversation_id, "output_id": output_id,
                              "code": "reflex_cancel_failed", "exception_type": type(exc).__name__})

    def _forget_reflex_work(self, reason: str) -> None:
        self._reflex_work.clear()
        self._reflex_terminal.clear()
        self._invalidate_reflex(reason)

    def note_user_speech(self, active: bool) -> None:
        """Le VAD du fournisseur entend l'utilisateur, ou ne l'entend plus."""

        self._user_speaking = bool(active)
        if self._user_speaking:
            self._user_quiet.clear()
            self._invalidate_reflex("user_speaking")
            reflex = self._reflex
            if reflex is not None:
                # L'utilisateur reprend la parole : l'accusé de sa phrase
                # précédente arriverait en travers de la nouvelle.
                self._reflex = None
                self._skip_reflex(reflex, "user_speaking")
        else:
            self._user_quiet.set()
            self._wakeup.set()

    async def abandon_turn(self, correlation_id: str | None) -> bool:
        """L'utilisateur a repris la parole pendant la réflexion : ce tour est abandonné.

        Trois gestes, dans cet ordre, parce que le dernier peut attendre le
        réseau et que les deux premiers rendent la main tout de suite :

        1. la corrélation est notée abandonnée, ce qui rend inéligible toute
           parole qui en vient — y compris celle qui traversait `/v1/events`
           au moment de l'interruption ;
        2. la file est replanifiée : les demandes déjà reçues pour ce tour
           sortent en `superseded`, et l'accusé de réception qui l'attendait
           est invalidé ;
        3. Core est prié d'abandonner la tâche du tour (`cancel_brain_turn`).
           Sans ce troisième geste, l'interruption ne ferait que **taire** le
           cerveau : il continuerait de réfléchir et sa réponse reviendrait
           plus tard, en travers de la question suivante.

        Ce qui tourne n'est pas tué : jobs et sous-agents vivent hors de la
        tâche du tour, et Core ne les touche pas (`BrainOrchestrator.cancel_turn`).

        Un échec du troisième geste est tracé sans rien casser : la file est
        déjà purgée localement, donc l'utilisateur a bien repris la main.
        """

        if not correlation_id or self._stopping:
            return False
        if correlation_id in self._abandoned_correlations:
            return False
        self._abandoned_correlations[correlation_id] = None
        while len(self._abandoned_correlations) > 64:
            self._abandoned_correlations.popitem(last=False)
        for queued in tuple(self._pending) + tuple(self._deferred.values()):
            if queued.correlation_id == correlation_id:
                self._defer(queued, SpeechCandidateStatus.SUPERSEDED, "turn_abandoned")
        self._invalidate_reflex("turn_abandoned", correlation_id=correlation_id)
        reflex = self._reflex
        if reflex is not None and reflex.correlation_id == correlation_id:
            self._reflex = None
            self._skip_reflex(reflex, "turn_abandoned")
        self._replan()
        cancel = getattr(self.core, "cancel_brain_turn", None)
        cancelled: object = None
        error: str | None = None
        if callable(cancel):
            try:
                result = await cancel(self.conversation_id, correlation_id=correlation_id)
                cancelled = bool((result or {}).get("cancelled")) if isinstance(result, dict) else None
            except Exception as exc:  # transport, 4xx, Core arrêté : jamais fatal ici
                error = f"{type(exc).__name__}: {exc}"
        self._trace(
            SPEECH_TURN_ABANDONED,
            "Tour du cerveau abandonné : l'utilisateur a repris la parole pendant la réflexion",
            level="warning" if error else "info",
            data={"conversation_id": self.conversation_id,
                  "session_id": str(getattr(self.session, "session_id", "")) or None,
                  "correlation_id": correlation_id,
                  "core_cancelled": cancelled,
                  "core_reachable": callable(cancel),
                  "error": error},
        )
        self._wakeup.set()
        return True

    @property
    def _without_output_final(self) -> bool:
        """La surface n'annonce jamais la fin d'une sortie (GPT-Live, duplex).

        Tout ce que l'ordonnanceur compte sur une fin de sortie y est faux :
        une identité de sortie du fournisseur ne se referme jamais, et une
        parole ne peut jamais être constatée « complète ». La surface, elle,
        restitue seule le texte entier en ajouts bornés et ordonnés
        (`live_frontend_session.append_segments`).
        """

        return bool(getattr(self.session, "requires_local_quiescence_without_output_final", False))

    def _output_still_alive(self, output_id: str) -> bool:
        if getattr(self.session, "active_output_id", None) == output_id:
            return True
        alive = self.output_alive
        return bool(alive is not None and alive(output_id))

    def _skip_reflex(self, reflex: _Reflex, reason: str) -> None:
        self._trace(
            REFLEX_SKIPPED,
            "Reflex skipped",
            data={"conversation_id": self.conversation_id,
                  "session_id": str(getattr(self.session, "session_id", "")) or None,
                  "correlation_id": reflex.correlation_id, "reason": reason},
        )

    # -- notifications venues du bridge -------------------------------------

    async def note_output_event(self, event: ProtocolEnvelope) -> None:
        """Suivre la vie des sorties vocales observées par le bridge.

        Le bridge est le seul consommateur du flux du fournisseur : lire
        `session.events()` ici en ouvrirait un second, et les deux boucles se
        voleraient les évènements. L'ordonnanceur est donc notifié.
        """

        payload = event.payload or {}
        output_id = str(payload.get("output_id") or "")
        if event.message_type == "realtime.audio":
            if self._active is not None and isinstance(self._active.request, ConversationCandidate):
                return  # No backend speech latency/known intended text for direct generation.
            # Le bridge ne relaie que le **premier** bloc audio de chaque
            # sortie : il n'y a donc rien à dédupliquer ici, et la marque est de
            # toute façon consommée par la mesure. Une sortie sans `speech_id`
            # est un réflexe de surface, qui n'a pas de demande de parole à
            # chronométrer.
            speech_id = str(payload.get("speech_id") or "")
            # La sortie en cours ne renseigne la corrélation que si c'est bien
            # elle qui joue : recopier celle d'une autre parole rattacherait la
            # mesure au mauvais tour, ce qui est pire que de ne rien dire.
            active = self._active if self._active is not None and self._active.request.id == speech_id else None
            self._latency.measure(
                LATENCY_FIRST_BRAIN_AUDIO,
                speech_id,
                kind=LATENCY_FIRST_BRAIN_AUDIO_KIND,
                data={
                    "conversation_id": self.conversation_id,
                    "session_id": str(getattr(self.session, "session_id", "")) or None,
                    "speech_id": speech_id or None,
                    "output_id": output_id or None,
                    "correlation_id": active.request.correlation_id if active is not None else None,
                    "work_id": active.request.work_id if active is not None else None,
                    "kind": active.request.kind.value if active is not None else None,
                },
            )
            return
        if event.message_type == "realtime.output_started":
            if output_id and not self._without_output_final:
                # Sans fin de sortie, rien ne retirerait jamais cette identité :
                # la file resterait occupée pour la vie de la session, et plus
                # une seule parole du cerveau ne serait dite après la première
                # sortie du fournisseur. La quiescence locale est déjà tenue
                # par le bridge, et l'utilisateur par `_user_speaking`.
                self._live_outputs.add(output_id)
                self._idle.clear()
            return
        if event.message_type != "realtime.response_done":
            return
        status = str(payload.get("status") or "unknown")
        if output_id:
            self._live_outputs.discard(output_id)
        if not self._live_outputs:
            self._idle.set()
        active = self._active
        if active is not None and output_id and output_id == active.output_id:
            active.status = status
            active.done.set()

    def note_interruption(self, cursor: PlaybackCursor | None) -> None:
        """Marquer la parole en cours coupée par l'utilisateur (spec §12, étape 1).

        Synchrone et sans point de suspension : le bridge l'appelle juste après
        avoir arrêté la lecture, et rien ici ne doit retarder la suite de la
        séquence d'interruption.

        Un curseur absent (pile sans identifiant de sortie, Décision 21) ou
        désignant une autre sortie — un réflexe de surface, qui n'a pas de
        `SpeechRequest` — marque quand même la parole du cerveau en cours : le
        haut-parleur est unique, ce qui a été coupé est ce qui jouait. Seules
        les millisecondes entendues restent alors inconnues, donc nulles, et
        une parole dont rien n'a été entendu n'est pas persistée.
        """

        active = self._active
        if active is None:
            return
        active.interrupted = True
        candidate = self._candidates.get(active.request.id)
        if candidate is not None:
            self._blocked_chains.add(candidate.chunk.chain_id)
        self._replan()
        if cursor is not None and cursor.speech_id in {active.request.id, active.output_id}:
            active.played_ms = cursor.played_ms

    # -- consommation des évènements Core -----------------------------------

    async def _consume_core_events(self) -> None:
        """Rester abonné à `/v1/events` tant que la voix est active.

        Le flux peut se taire sans erreur : `CoreEventBus` désabonne un abonné
        dont la file déborde, et `events()` rend simplement la main quand le
        websocket se ferme (Décision 25). Une fin de boucle est donc traitée
        comme une coupure, pas comme un arrêt demandé — seule l'annulation de
        la tâche arrête cet abonnement.
        """

        while True:
            stream: AsyncIterator[ProtocolEnvelope] | None = None
            try:
                stream = self.core.events(on_connected=self._subscription_ready)
                async for envelope in stream:
                    await self.handle_core_event(envelope)
            except asyncio.CancelledError:
                await self._close_stream(stream)
                raise
            except Exception as exc:
                self._trace(
                    STREAM_FAILED,
                    f"Flux d'évènements Core interrompu: {type(exc).__name__}: {exc}",
                    level="warning",
                    data={"conversation_id": self.conversation_id, "code": "core_event_stream_failed"},
                )
            else:
                self._trace(
                    STREAM_CLOSED,
                    "Flux d'évènements Core fermé sans erreur : réabonnement",
                    level="warning",
                    data={"conversation_id": self.conversation_id, "code": "core_event_stream_closed"},
                )
            self._stream_connected = False
            self._source_unknown("stream_gap")
            await self._close_stream(stream)
            # Décision 31 : pas de rejeu. Ce qui a été manqué est perdu, donc
            # ce qui reste en file et n'est plus forcément vrai est jeté.
            self._drop_transient(reason="stream_gap")
            self._forget_reflex_work("stream_gap")
            # Attente de reconnexion volontairement sur `asyncio.sleep` et non
            # sur l'horloge injectée : celle-ci sert à dater et à comparer des
            # TTL, et une horloge de test qui « dort » instantanément
            # transformerait cette boucle en attente active qui ne rendrait
            # jamais la main à l'ordonnanceur asyncio.
            await asyncio.sleep(self.reconnect_delay_s)

    async def _close_stream(self, stream: AsyncIterator[ProtocolEnvelope] | None) -> None:
        aclose = getattr(stream, "aclose", None)
        if aclose is None:
            return
        try:
            await aclose()
        except Exception as exc:
            # Fermer un générateur déjà mort ne doit pas empêcher le
            # réabonnement, mais l'anomalie reste visible.
            self._trace(
                STREAM_FAILED,
                f"Fermeture du flux d'évènements Core en erreur: {type(exc).__name__}: {exc}",
                level="warning",
                data={"conversation_id": self.conversation_id, "code": "core_event_stream_close_failed"},
            )

    async def handle_core_event(self, envelope: ProtocolEnvelope) -> None:
        """Router un évènement Core. Point d'entrée unique, aussi pour les tests."""

        if self._stopping:
            return
        message_type = envelope.message_type
        if not message_type.startswith(BRAIN_EVENT_PREFIX) and message_type != "voice.turn.admitted":
            return
        payload = envelope.payload or {}
        conversation_id = str(payload.get("conversation_id") or envelope.conversation_id or "")
        if conversation_id and conversation_id != self.conversation_id:
            self._trace(
                SPEECH_IGNORED,
                "Évènement cerveau d'une autre conversation",
                data={
                    "conversation_id": conversation_id,
                    "expected_conversation_id": self.conversation_id,
                    "message_type": message_type,
                },
            )
            return

        # Décision 32 : le cerveau qui travaille est de l'activité utile. Le
        # délai repart du **dernier** évènement, donc un cerveau muet finit
        # quand même par rendre la session au fond.
        if message_type == "brain.source.changed":
            self.update_speech_context(payload)
        elif message_type in (BRAIN_TURN_ACCEPTED, BRAIN_INTENT_REVISED):
            self._note_revision(payload.get("revision"))
            self.update_speech_context(payload)
        elif message_type == BRAIN_STATE_UPDATED:
            self._note_revision(payload.get("revision"))
        await self._rearm_activity()
        if self._stopping:
            return

        if message_type == BRAIN_SPEECH_REQUESTED:
            request = self._read_request(payload)
            if request is not None:
                self._remember(self._core_speech_ids, request.id, None)
                # Borne de départ de la mesure 3, posée avant la mise en file :
                # l'attente du silence et le tri des demandes font partie du
                # délai que l'utilisateur subit, ils ne s'en retranchent pas.
                self._latency.mark(LATENCY_FIRST_BRAIN_AUDIO, request.id)
                self._enqueue(request)
        elif message_type == BRAIN_TURN_ACCEPTED:
            current = self._reflex or self._live_reflex
            if current is not None and current.correlation_id != payload.get("correlation_id"):
                self._invalidate_reflex("new_turn")
            self._note_revision(payload.get("revision"))
            # Un nouveau tour utilisateur faisant autorité est une révision
            # d'intention : ce qui attendait d'être dit sur l'intention
            # précédente ne l'est plus (spec section 6).
            self._replan()
        elif message_type == BRAIN_INTENT_REVISED:
            self._invalidate_reflex("intent_revised")
            for field in ("superseded_work_ids", "cancelled_work_ids"):
                for work_id in payload.get(field, ()) if isinstance(payload.get(field), (list, tuple)) else ():
                    if work_id in self._reflex_work:
                        correlation = self._reflex_work[work_id][0]
                        self._reflex_work[work_id] = (correlation, False)
                        self._reflex_terminal[correlation] = True
            while len(self._reflex_terminal) > 128:
                self._reflex_terminal.popitem(last=False)
            self._note_revision(payload.get("revision"))
            # Core a désigné le travail dont la parole n'est plus vraie. C'est
            # une décision du cerveau, pas une heuristique de surface : elle
            # emporte donc aussi les paroles durables (résultat, question), que
            # rien d'autre ne permet de retirer (Décision 14). Le travail
            # `retained` n'est jamais touché.
            # Work generation invalidations come from the exact dependency context, not reusable IDs.
            self._replan()
        elif message_type == BRAIN_STATE_UPDATED:
            self._note_revision(payload.get("revision"))
        elif message_type in (BRAIN_WORK_STARTED, BRAIN_WORK_COMPLETED, BRAIN_WORK_FAILED):
            correlation, work_id = payload.get("correlation_id"), payload.get("work_id")
            if isinstance(correlation, str) and correlation and len(correlation) <= 256 and isinstance(work_id, str) and work_id and len(work_id) <= 256:
                active = message_type == BRAIN_WORK_STARTED
                # A late start cannot resurrect work already observed terminal.
                previous = self._reflex_work.get(work_id)
                if previous is not None and not previous[1]:
                    active = False
                self._reflex_work[work_id] = (correlation, active)
                while len(self._reflex_work) > 128:
                    self._reflex_work.popitem(last=False)
                if not active:
                    self._reflex_terminal[correlation] = True
                    while len(self._reflex_terminal) > 128:
                        self._reflex_terminal.popitem(last=False)
                    self._invalidate_reflex("work_terminal", correlation_id=correlation)
                self._wakeup.set()
        # `brain.work.*` n'est pas de la parole : ce sont des faits. Core émet
        # lui-même la `brain.speech.requested` quand un échec mérite d'être dit
        # (Décision 13) ; en fabriquer une ici remettrait de la politique de
        # parole dans la surface.

    def _read_request(self, payload: dict) -> SpeechRequest | None:
        """Reconstruire une demande de parole, ou dire pourquoi elle est inutilisable.

        Une charge utile invalide (texte vide, priorité inconnue) est un défaut
        de contrat côté Core, pas une raison de tuer l'abonnement : elle est
        signalée et ignorée.
        """

        raw = dict(payload)
        if not raw.get("conversation_id"):
            raw["conversation_id"] = self.conversation_id
        try:
            # Défense en profondeur : Core date lui-même la péremption de la
            # parole transitoire, mais un backend futur pourrait l'oublier. Une
            # progression sans échéance resterait alors prononçable
            # indéfiniment, ce que la Décision 31 interdit. Une échéance déjà
            # présente n'est jamais écrasée.
            return SpeechRequest.from_payload(raw).with_default_ttl(self.transient_ttl_s)
        except ValueError as exc:
            self._trace(
                SPEECH_IGNORED,
                f"Demande de parole invalide: {exc}",
                level="warning",
                data={
                    "conversation_id": self.conversation_id,
                    "speech_id": raw.get("speech_id"),
                    "reason": "invalid_payload",
                },
            )
            return None

    async def _rearm_activity(self) -> None:
        if self.on_brain_activity is None:
            return
        value = self.on_brain_activity()
        if hasattr(value, "__await__"):
            await value

    def _note_revision(self, value: object) -> None:
        """Suivre la révision monotone et détecter un trou (Décision 31).

        Un saut prouve qu'au moins un évènement a été manqué. Rien n'est
        rejoué : on jette ce qui n'est probablement plus vrai et on le dit au
        journal. La reprise de contexte se fait par l'état de Core, pas par une
        parole que la surface inventerait.
        """

        if not isinstance(value, int) or isinstance(value, bool):
            return
        previous = self._last_revision
        if previous is not None and value > previous + 1:
            self._forget_reflex_work("revision_gap")
            self._source_unknown("revision_gap")
            self._trace(
                REVISION_GAP,
                "Révision de l'état cerveau discontinue : des évènements ont été manqués",
                level="warning",
                data={
                    "conversation_id": self.conversation_id,
                    "expected_revision": previous + 1,
                    "received_revision": value,
                    "code": "brain_revision_gap",
                },
            )
            self._drop_transient(reason="revision_gap")
        if previous is None or value > previous:
            self._last_revision = value

    # -- file ---------------------------------------------------------------

    def presentation_snapshot(self) -> dict:
        """Bounded diagnostics; outcome ownership and text remain in Core."""
        return {"source_complete": self._source_complete,
                "current_source": self._current_source.to_payload() if self._current_source else None,
                "candidates": [{**self._fields(item.request), "status": item.status.value,
                    "reason": item.reason, "outcome_id": item.request.outcome_id,
                    "source": item.request.source.to_payload() if item.request.source else None,
                    "chunk": item.chunk.to_payload(),
                    "age_ms": max(0, int((self.clock.now() - item.request.created_at).total_seconds() * 1000))}
                    for item in self._candidates.values()]}

    def update_speech_context(self, payload: dict) -> None:
        """Apply Core intent authority, never the general working-state revision."""
        if self._stopping:
            return
        try:
            if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1 or payload.get("conversation_id") != self.conversation_id:
                raise ValueError("Invalid source context envelope")
            complete = payload["source_complete"]
            if type(complete) is not bool:
                raise ValueError("Invalid completeness")
            source = SpeechSource.from_payload(payload["current_speech_source"]) if payload["current_speech_source"] is not None else None
            raw = payload["invalidated_dependencies"]
            if not isinstance(raw, list) or len(raw) > 256:
                raise ValueError("Invalid dependencies")
            invalid = {SpeechDependency.from_payload(item) for item in raw}
            if len(self._invalidated_dependencies | invalid) > 4096:
                raise ValueError("Dependency retention exhausted")
            self._invalidated_dependencies.update(invalid)
            if source is not None and source.intent_epoch < self._intent_watermark:
                self._replan()  # Old snapshots may add tombstones, never roll intent backwards.
                return
            if source is not None and source.intent_epoch == self._intent_watermark and self._current_source is not None and source != self._current_source:
                raise ValueError("Conflicting source at the same epoch")
            if source is None and self._intent_watermark >= 0:
                raise ValueError("Current source disappeared")
            self._current_source = source
            if source is not None:
                self._intent_watermark = source.intent_epoch
            self._source_complete = complete
        except (ValueError, TypeError, KeyError):
            self._source_complete = False
        self._update_analysis_source()
        self._replan()

    def _update_analysis_source(self) -> None:
        analysis = getattr(self.session, "analysis", None)
        if analysis is not None:
            analysis.update_source(source=self._current_source, source_complete=self._source_complete,
                                   invalidated_dependencies=tuple(self._invalidated_dependencies)[:256])

    def _subscription_ready(self) -> None:
        if self._stopping:
            return
        self._stream_connected = True
        self._source_unknown("subscribed")

    def _source_unknown(self, reason: str) -> None:
        self._source_generation += 1
        self._source_complete = False
        self._update_analysis_source()
        self._replan()
        if self._source_refresh is not None and not self._source_refresh.done():
            self._source_refresh.cancel()
        if self._running and self._stream_connected and len(self._source_queries) < 8:
            self._source_refresh = asyncio.create_task(self._refresh_source(self._source_generation), name="jarvis-speech-source")
            self._source_queries.add(self._source_refresh)
            self._source_refresh.add_done_callback(self._source_queries.discard)

    async def _refresh_source(self, generation: int) -> None:
        query = getattr(self.core, "speech_context", None)
        if not callable(query):
            return
        try:
            payload = await asyncio.wait_for(query(self.conversation_id), self.output_timeout_s)
            if self._running and self._stream_connected and generation == self._source_generation:
                self.update_speech_context(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if generation != self._source_generation or not self._running:
                return
            self._source_complete = False
            self._replan()
            self._trace(SPEECH_DECIDED, "Speech source unavailable", level="warning",
                        data={"conversation_id": self.conversation_id, "reason": "source_query_failed", "exception_type": type(exc).__name__})

    def _eligibility(self, request: SpeechRequest) -> tuple[SpeechCandidateStatus, str]:
        if request.is_expired(self.clock.now()):
            return SpeechCandidateStatus.EXPIRED, "ttl"
        candidate = self._candidates.get(request.id)
        if candidate is not None and candidate.chunk.chain_id in self._blocked_chains:
            return SpeechCandidateStatus.SUPERSEDED, "interrupted_chain"
        if request.correlation_id and request.correlation_id in self._abandoned_correlations:
            # Tour abandonné pendant la réflexion : même une parole déjà rédigée
            # ne répond plus à ce que l'utilisateur vient de dire.
            return SpeechCandidateStatus.SUPERSEDED, "turn_abandoned"
        if request.source is None:
            return SpeechCandidateStatus.DEFERRED, "unknown_source"
        if not self._source_complete or self._current_source is None:
            return SpeechCandidateStatus.DEFERRED, "source_state_unknown"
        if any(dependency in self._invalidated_dependencies for dependency in request.source.dependencies):
            return SpeechCandidateStatus.SUPERSEDED, "dependency_revoked"
        carried_over = False
        if (request.source.intent_id, request.source.intent_epoch) != (self._current_source.intent_id, self._current_source.intent_epoch):
            if isinstance(request, ConversationCandidate):
                if request.source.intent_epoch > self._intent_watermark:
                    return SpeechCandidateStatus.DEFERRED, "source_state_unknown"
                return SpeechCandidateStatus.SUPERSEDED, "stale_source"
            if request.kind in TRANSIENT_KINDS:
                # Une progression ou un accusé décrivent un instant. L'instant
                # est passé : leur vérité s'est évaporée toute seule.
                return SpeechCandidateStatus.SUPERSEDED, "stale_source"
            if request.source.intent_epoch > self._intent_watermark:
                # Intention plus récente que ce que la surface connaît : elle
                # arrive, elle sera replanifiée. Ce n'est pas du passé.
                return SpeechCandidateStatus.DEFERRED, "source_state_unknown"
            # Parole durable d'une intention passée. Une intention ne revient
            # jamais (`intent_id == turn_id`, et l'époque ne recule pas) : la
            # différer, c'est l'enterrer en silence — 22 élocutions du cerveau
            # ont fini là, une seule a été dite. Décision de l'utilisateur du
            # 19/09/2026 : « une réponse sans retard faut qu'elle soit dite si
            # c'est cohérent avec le contexte ». La cohérence n'est pas une
            # règle d'ancienneté que la surface pourrait appliquer : un
            # résultat, une erreur ou une question restent vrais tant que le
            # cerveau ne les a pas retirés (Décision 14), et le retrait se fait
            # par désignation explicite du `work_id` (`BrainEventKind.SUPERSEDED`,
            # `jarvis/domain/v2.py`), jamais en bloc. La parole est donc
            # reportée sur l'intention courante, après ce que celle-ci a déjà
            # en file, et le cerveau garde la main pour la retirer.
            carried_over = True
        if isinstance(request, ConversationCandidate):
            available = callable(getattr(self.session, "request_conversation", None)) and callable(getattr(self.session, "invalidate_unstarted_output", None))
            return (SpeechCandidateStatus.ELIGIBLE, "current_intent") if available else (SpeechCandidateStatus.DEFERRED, "output_admission_unavailable")
        if not callable(getattr(self.session, "speak_reserved", None)) or not callable(getattr(self.session, "invalidate_unstarted_output", None)):
            return SpeechCandidateStatus.DEFERRED, "output_admission_unavailable"
        return SpeechCandidateStatus.ELIGIBLE, "carried_over" if carried_over else "current_intent"

    def _decision(self, request: SpeechRequest, status: SpeechCandidateStatus, reason: str) -> None:
        if isinstance(request, ConversationCandidate):
            self._trace("voice.conversation.presentation", "Direct conversation presentation", data={**self._fields(request), "status": status.value, "reason": reason})
            return
        candidate = self._candidates.get(request.id)
        if candidate is None or (candidate.status is status and candidate.reason == reason):
            return
        candidate.status, candidate.reason = status, reason
        terminal_channel = {SpeechCandidateStatus.EXPIRED: SPEECH_EXPIRED, SpeechCandidateStatus.SUPERSEDED: SPEECH_SUPERSEDED}.get(status)
        if terminal_channel is not None:
            closed = _T.MOUTH_SPEECH_EXPIRED if status is SpeechCandidateStatus.EXPIRED else _T.MOUTH_SPEECH_SUPERSEDED
            self._trace(terminal_channel, "Speech presentation retired", data={**self._fields(request), "reason": reason,
                        **self._mouth_event(closed, request, terminal_channel, reason=reason)})
        if status is SpeechCandidateStatus.DEFERRED and request.kind is SpeechKind.ERROR:
            # Une panne muette est le pire des cas : on ne sait pas qu'on ne sait
            # pas. Le 16/09/2026 à 07:38:57, la parole d'erreur du handover est
            # restée ici, `deferred`/`stale_source`, et personne n'a rien
            # entendu. Depuis la Décision de l'utilisateur du 19/09/2026, une
            # intention passée ne diffère plus rien ; ce qui reste différé l'est
            # pour une source inconnue ou une admission absente, donc pour un
            # temps borné — mais cela ne doit toujours pas passer pour un
            # silence normal.
            self._trace(SPEECH_ERROR_WITHHELD, "Erreur non prononcée : son intention n'est plus courante",
                        level="warning", data={**self._fields(request), "reason": reason,
                                               "outcome_id": request.outcome_id})
        if terminal_channel is not None:
            self._settle_unspoken(request, status.value, reason)
        self._trace(SPEECH_DECIDED, "Speech presentation decision", data={**self._fields(request),
            "status": status.value, "reason": reason, "outcome_id": request.outcome_id,
            "intent_id": request.source.intent_id if request.source else None,
            "intent_epoch": request.source.intent_epoch if request.source else None,
            "chunk": candidate.chunk.to_payload(),
            "age_ms": max(0, int((self.clock.now() - request.created_at).total_seconds() * 1000))})

    def _settle_unspoken(self, request: SpeechRequest, status: str, reason: str) -> None:
        """Solder à voix haute une parole durable qui meurt sans avoir été tentée.

        C'est un solde, pas un incident de file : il est dit une fois, en clair,
        avec le texte qui n'a pas été prononcé et la raison de son retrait.
        « Une réponse complète jetée mérite au minimum le même traitement que la
        parole d'erreur » (retour du 19/09/2026) — sans quoi cela « passe pour
        un silence normal ». Une progression ou un accusé ne sont pas soldés :
        leur vérité s'évapore d'elle-même, et le dire à chaque tour noierait le
        signal.
        """

        if request.kind in TRANSIENT_KINDS or request.id in self._attempted_ids:
            return
        self._trace(SPEECH_ABANDONED, "Réponse du cerveau soldée sans avoir été dite",
                    level="warning", data={**self._fields(request), "reason": reason, "status": status,
                                           "outcome_id": request.outcome_id, "text": public_text(request.text)})

    def _retain_candidate(self, candidate: _Candidate) -> bool:
        while len(self._candidates) >= 256:
            disposable = next((key for key, value in self._candidates.items()
                if value.status in {SpeechCandidateStatus.SUPERSEDED, SpeechCandidateStatus.EXPIRED,
                                    SpeechCandidateStatus.COMPLETED, SpeechCandidateStatus.INTERRUPTED}), None)
            if disposable is None:
                return False
            del self._candidates[disposable]
        self._candidates[candidate.request.id] = candidate
        return True

    def _defer(self, request: SpeechRequest, status: SpeechCandidateStatus, reason: str) -> None:
        if request in self._pending:
            self._pending.remove(request)
        self._queued_at.pop(request.id, None)
        self._deferred.pop(request.id, None)
        if isinstance(request, ConversationCandidate):
            self._decision(request, status, reason)
            return  # Direct input is never silently replayed after freshness loss.
        if status is SpeechCandidateStatus.DEFERRED:
            if len(self._deferred) >= 64:
                status, reason = SpeechCandidateStatus.SUPERSEDED, "deferred_capacity"
            else:
                self._deferred[request.id] = request
        self._decision(request, status, reason)

    def _on_current_intent(self, request: SpeechRequest) -> bool:
        source, current = request.source, self._current_source
        return (source is not None and current is not None
                and (source.intent_id, source.intent_epoch) == (current.intent_id, current.intent_epoch))

    def _may_supersede(self, newer: SpeechRequest, older: SpeechRequest) -> bool:
        """Qui a autorité pour remplacer qui, maintenant que le passé parle encore.

        Même origine exacte : la règle d'origine, inchangée. Origines
        différentes : seule une parole de l'intention **courante** remplace une
        parole reportée d'une intention passée — jamais l'inverse. Sans cette
        dissymétrie, un vieux résultat arrivé en retard effacerait le travail
        courant (`_enqueue`, « a late old result cannot remove current work ») ;
        sans le report, le cerveau redirait l'ancienne version d'un même travail
        après la nouvelle.
        """

        if not isinstance(newer, SpeechRequest) or not isinstance(older, SpeechRequest) or newer.id == older.id:
            return False
        if newer.source == older.source:
            return newer.supersedes(older)
        if not (self._on_current_intent(newer) and not self._on_current_intent(older)):
            return False
        # Entre deux origines, l'autorité vient de l'intention, pas de l'heure
        # de rédaction : une réponse reportée arrive forcément « après » celle
        # de l'intention courante, et `supersedes` la ferait gagner sur sa seule
        # date. La même clé de supersession désigne le même emplacement de
        # parole : l'intention courante l'occupe.
        return (newer.supersedes(older)
                or (newer.supersedes_key is not None and newer.supersedes_key == older.supersedes_key)
                or (newer.work_id is not None and newer.work_id == older.work_id))

    def _replan(self) -> None:
        for request in tuple(self._pending):
            status, reason = self._eligibility(request)
            if isinstance(request, ConversationCandidate) and reason == "source_state_unknown":
                continue  # Existing subscription barrier will replan this bounded candidate.
            if status is not SpeechCandidateStatus.ELIGIBLE:
                self._defer(request, status, reason)
        for request in tuple(self._deferred.values()):
            if request.id in self._attempted_ids:
                continue  # Re-expression requires a new Core request/chain identity.
            status, reason = self._eligibility(request)
            if status is SpeechCandidateStatus.ELIGIBLE and len(self._pending) < 64:
                others = [queued for queued in self._pending if isinstance(queued, SpeechRequest)
                          and self._candidates[queued.id].chunk.chain_id != self._candidates[request.id].chunk.chain_id]
                if any(self._may_supersede(queued, request) for queued in others):
                    self._defer(request, SpeechCandidateStatus.SUPERSEDED, "superseded_on_arrival")
                    continue
                for queued in others:
                    if self._may_supersede(request, queued):
                        self._defer(queued, SpeechCandidateStatus.SUPERSEDED, "superseded")
                active = self._active
                if active is not None and isinstance(active.request, SpeechRequest) and self._may_supersede(request, active.request):
                    self._invalidate_presentation(active, "superseded")
                self._deferred.pop(request.id, None)
                self._pending.append(request)
                self._decision(request, status, reason)
                self._note_queued(request)
            elif status is not SpeechCandidateStatus.ELIGIBLE:
                self._defer(request, status, reason)
        active = self._active
        if active is not None:
            status, reason = self._eligibility(active.request)
            if status is not SpeechCandidateStatus.ELIGIBLE:
                self._invalidate_presentation(active, reason)
        if any(self._eligibility(request)[0] is SpeechCandidateStatus.ELIGIBLE for request in self._pending):
            self._invalidate_reflex("useful_content_ready")
            self._wakeup.set()

    def _invalidate_presentation(self, active: _ActiveSpeech, reason: str) -> None:
        if active.output_id in self._presentation_cancelled or active.admission is None or not active.admission.invalidate():
            return  # An attempted native write is no longer proven unplayed.
        self._presentation_cancelled.add(active.output_id)
        self._decision(active.request, SpeechCandidateStatus.DEFERRED, reason)
        task = asyncio.create_task(self._cancel_presentation(active.output_id), name="jarvis-speech-cancel")
        self._presentation_cancels.add(task)
        task.add_done_callback(self._presentation_cancels.discard)

    async def _cancel_presentation(self, output_id: str) -> None:
        try:
            await asyncio.wait_for(self.session.invalidate_unstarted_output(output_id), self.output_timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._trace(SPEAK_FAILED, "Speech cancellation failed", level="warning",
                data={"output_id": output_id, "reason": "presentation_cancel_failed", "exception_type": type(exc).__name__})

    def _expire_presentation(self, active: _ActiveSpeech) -> None:
        self._presentation_expiries.pop(active.output_id, None)
        self._invalidate_presentation(active, "ttl")

    def enqueue_controller_speech(self, request: SpeechRequest) -> None:
        """Present a source-bound controller notice through normal admission."""
        self._enqueue(request)
        self._wakeup.set()

    def _enqueue(self, request: SpeechRequest) -> None:
        if self._stopping:
            return
        if request.id in self._seen_speech_ids or request.conversation_id != self.conversation_id:
            self._trace(SPEECH_IGNORED, "Speech request ignored", data={**self._fields(request), "reason": "duplicate_speech_id" if request.id in self._seen_speech_ids else "other_conversation"})
            return
        if len(self._seen_speech_ids) >= 4096:
            self._trace(SPEECH_IGNORED, "Speech identity capacity reached", data={**self._fields(request), "reason": "session_capacity"})
            return
        self._seen_speech_ids.add(request.id)
        try:
            spans = request.chunks or semantic_text_spans(request.text)
        except ValueError:
            self._trace(SPEECH_DECIDED, "Speech presentation deferred", data={**self._fields(request), "status": "deferred", "reason": "semantic_chunk_limit", "outcome_id": request.outcome_id})
            return
        if len(spans) > 1 and self._without_output_final:
            # Une chaîne de paragraphes suppose qu'on puisse constater la fin
            # du précédent. Sans elle, chaque maillon finit « interrompu », la
            # chaîne est bloquée, et seul le premier paragraphe d'un résultat
            # était dit — le reste partait en `interrupted_chain`. La surface
            # découpe elle-même le texte en ajouts bornés : on la laisse faire.
            # Fusion bornée par `MAX_SPEECH_CHUNK_TEXT`, qui est aussi la borne
            # du texte annoncé au ledger (`register_speech`).
            merged: list[SpeechTextSpan] = []
            for span in spans:
                head = merged[-1] if merged else None
                if head is not None and span.end - head.start <= MAX_SPEECH_CHUNK_TEXT:
                    merged[-1] = SpeechTextSpan(head.start, span.end)
                else:
                    merged.append(span)
            spans = tuple(merged)
        if len(self._seen_speech_ids) + len(spans) > 4096:
            return
        # Replacement needs eligible authority (`_may_supersede`); a late old result cannot remove current work.
        incoming_status, _ = self._eligibility(request)
        existing = tuple(item for item in self._pending if isinstance(item, SpeechRequest)) + tuple(self._deferred.values())
        if incoming_status is SpeechCandidateStatus.ELIGIBLE and any(self._may_supersede(queued, request) for queued in existing):
            self._trace(SPEECH_SUPERSEDED, "Speech superseded on arrival", data={
                **self._fields(request), "reason": "superseded_on_arrival",
                **self._mouth_event(_T.MOUTH_SPEECH_SUPERSEDED, request, SPEECH_SUPERSEDED, reason="superseded_on_arrival")})
            self._settle_unspoken(request, SpeechCandidateStatus.SUPERSEDED.value, "superseded_on_arrival")
            return
        for queued in existing:
            if incoming_status is SpeechCandidateStatus.ELIGIBLE and self._may_supersede(request, queued):
                self._defer(queued, SpeechCandidateStatus.SUPERSEDED, "superseded")
        active = self._active
        if incoming_status is SpeechCandidateStatus.ELIGIBLE and active is not None and isinstance(active.request, SpeechRequest) and self._may_supersede(request, active.request):
            self._invalidate_presentation(active, "superseded")
        self._chain_next[request.id] = 0
        for index, span in enumerate(spans):
            identifier = request.id if len(spans) == 1 else str(uuid.uuid5(uuid.NAMESPACE_URL, f"jarvis-speech:{request.id}:{index}:{span.start}:{span.end}"))
            self._seen_speech_ids.add(identifier)
            child = replace(request, id=identifier, text=request.text[span.start:span.end], chunks=())
            candidate = _Candidate(child, SpeechCandidateStatus.DEFERRED, "received", SpeechChunk(request.id, index, len(spans), span))
            if not self._retain_candidate(candidate):
                self._trace(SPEECH_IGNORED, "Speech candidate capacity reached", data={**self._fields(child), "reason": "candidate_capacity"})
                break
            status, reason = self._eligibility(child)
            if status is SpeechCandidateStatus.ELIGIBLE and len(self._pending) < 64:
                self._pending.append(child)
                self._decision(child, status, reason)
                self._note_queued(child)
                self._latency.mark(LATENCY_FIRST_BRAIN_AUDIO, child.id)
            else:
                self._defer(child, status if status is not SpeechCandidateStatus.ELIGIBLE else SpeechCandidateStatus.DEFERRED,
                            reason if status is not SpeechCandidateStatus.ELIGIBLE else "queue_capacity")
        self._replan()

    def _drop_transient(self, *, reason: str) -> None:
        """Jeter la parole transitoire que l'évènement courant rend caduque."""

        for queued in tuple(self._pending) + tuple(self._deferred.values()):
            if isinstance(queued, ConversationCandidate) or queued.kind in TRANSIENT_KINDS:
                self._defer(queued, SpeechCandidateStatus.SUPERSEDED, reason)

    def _expire_all(self, *, reason: str) -> None:
        for queued in tuple(self._pending):
            self._decision(queued, SpeechCandidateStatus.EXPIRED, reason)
        self._pending.clear()

    def _pop_next(self) -> SpeechRequest | None:
        self._replan()
        eligible = [request for request in self._pending
                    if (isinstance(request, ConversationCandidate) and self._eligibility(request)[0] is SpeechCandidateStatus.ELIGIBLE)
                    or (isinstance(request, SpeechRequest) and self._candidates[request.id].chunk.index == self._chain_next.get(self._candidates[request.id].chunk.chain_id))]
        if not eligible or self._user_speaking:
            return None
        direct = [item for item in eligible if isinstance(item, ConversationCandidate)]
        chosen = direct[-1] if direct else min(eligible, key=lambda item: item.ordering_key)
        self._pending.remove(chosen)
        self._decision(chosen, SpeechCandidateStatus.SELECTED, "priority_then_fifo")
        return chosen

    # -- livraison ----------------------------------------------------------

    async def _deliver_pending(self) -> None:
        """Boucle de livraison : seule voie d'accès à `speak()`."""

        while True:
            await self._wait_for_work()
            while self._pending:
                # Attendre le silence **avant** de choisir : une attente longue
                # peut voir arriver un résultat qui périme la progression qu'on
                # aurait sinon déjà retirée de la file.
                await self._wait_until_silent()
                request = self._pop_next()
                if request is None:
                    break
                await self._speak(request)
            await self._maybe_speak_reflex()

    async def _wait_for_work(self) -> None:
        """Attendre une demande de parole, ou l'échéance de l'accusé en attente."""

        reflex = self._reflex
        if reflex is None or self._pending:
            await self._wakeup.wait()
        else:
            timeout = max(0.0, reflex.next_check - asyncio.get_running_loop().time())
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        self._wakeup.clear()

    async def _maybe_speak_reflex(self) -> None:
        """Dire l'accusé de réception s'il est dû et encore utile."""

        reflex = self._reflex
        if reflex is None:
            return
        if asyncio.get_running_loop().time() < reflex.due:
            return
        decision = self._decide_reflex(reflex)
        self._record_reflex_decision(reflex, decision, "deadline")
        if decision.action is not ReflexAction.PREAMBLE:
            if decision.reason == "work_unconfirmed":
                reflex.next_check = reflex.expires
            else:
                self._reflex = None
            return
        await self._wait_until_silent()
        if self._reflex is not reflex:
            # Retiré pendant l'attente : le cerveau a répondu, l'utilisateur a
            # repris la parole, ou un tour plus récent l'a remplacé.
            return
        decision = self._decide_reflex(reflex)
        self._record_reflex_decision(reflex, decision, "before_start")
        if decision.action is not ReflexAction.PREAMBLE:
            self._reflex = None
            return
        reflex.output_id = str(uuid.uuid4())
        reflex.admission = OutputAdmission(expires_at=reflex.expires)
        self._reflex_admissions[reflex.output_id] = reflex.admission
        self._reflex_used.add(reflex.correlation_id)
        self._live_reflex = reflex
        self._reflex_expiries[reflex.output_id] = asyncio.get_running_loop().call_at(reflex.expires, self._expire_reflex, reflex)
        try:
            output_id = await self.session.speak_reflex(transcript=reflex.transcript, avoid=reflex.avoid,
                                                       output_id=reflex.output_id, correlation_id=reflex.correlation_id)  # type: ignore[attr-defined]
        except asyncio.CancelledError:
            self._invalidate_reflex("start_cancelled")
            raise
        except Exception as exc:
            self._invalidate_reflex("start_failed")
            self._trace(
                SPEAK_FAILED,
                "La surface n'a pas pu démarrer le préambule",
                level="warning",
                data={"conversation_id": self.conversation_id, "correlation_id": reflex.correlation_id, "code": "reflex_speak_failed", "exception_type": type(exc).__name__},
            )
            return
        if self._reflex is reflex:
            self._reflex = None
        if output_id != reflex.output_id:
            self._invalidate_reflex("output_identity_mismatch")
            self._trace(SPEAK_FAILED, "Reserved reflex output identity changed", level="error",
                        data={"code": "reflex_output_identity_mismatch", "correlation_id": reflex.correlation_id})
            return
        if reflex.admission.state is OutputAdmissionState.INVALIDATED:
            return
        # Comme pour une parole du cerveau : marquer la sortie tout de suite
        # empêche un `speak()` de partir avant que le fournisseur ne confirme.
        self._live_outputs.add(str(output_id))
        self._idle.clear()
        self._trace(
            REFLEX_STARTED,
            "Preamble generation requested",
            data={"conversation_id": self.conversation_id,
                  "session_id": str(getattr(self.session, "session_id", "")) or None,
                  "correlation_id": reflex.correlation_id, "output_id": str(output_id),
                  **self._reflex_event(reflex, str(output_id))},
        )

    def _expire_reflex(self, reflex: _Reflex) -> None:
        self._reflex_expiries.pop(reflex.output_id, None)
        self._invalidate_reflex("too_late", correlation_id=reflex.correlation_id)

    async def _wait_until_silent(self) -> None:
        """Attendre que plus rien ne joue et que l'utilisateur ait fini de parler.

        Ne pas lancer une phrase par-dessus l'utilisateur : son tour à lui
        arrive, et ce qu'on dirait maintenant serait coupé par le barge-in.
        L'attente est bornée par `user_speech_hold_s`.
        """

        await self._wait_for_idle_output()
        if not self._user_speaking:
            return
        try:
            await asyncio.wait_for(self._user_quiet.wait(), timeout=self.user_speech_hold_s)
        except asyncio.TimeoutError:
            return
        await self._wait_for_idle_output()

    async def _wait_for_idle_output(self) -> None:
        """Attendre que plus aucune sortie ne joue, réflexe de surface compris.

        Une sortie ouverte dont la fin ne revient jamais — glitch fournisseur,
        websocket coupé au mauvais moment — condamnerait sinon l'ordonnanceur au
        silence définitif. Le délai ne conclut rien tout seul : il déclenche une
        relecture de la comptabilité de la session, seule à savoir si la surface
        parle encore.
        """

        while True:
            try:
                await asyncio.wait_for(self._idle.wait(), timeout=self.output_timeout_s)
                return
            except asyncio.TimeoutError:
                # `active_output_id` d'une surface sans fin de sortie ne désigne
                # que la dernière sortie *observée* : elle ne redevient jamais
                # nulle, et la prendre pour une lecture en cours condamnerait
                # cette attente à ne jamais finir.
                playing = None if self._without_output_final else getattr(self.session, "active_output_id", None)
                if playing is not None or any(
                    self._output_still_alive(output_id) for output_id in self._live_outputs
                ):
                    continue
                self._trace(
                    OUTPUT_STALLED,
                    "Sortie vocale sans fin annoncée : la file de parole est débloquée",
                    level="warning",
                    data={
                        "conversation_id": self.conversation_id,
                        "session_id": str(getattr(self.session, "session_id", "")) or None,
                        "live_outputs": sorted(self._live_outputs),
                        "code": "speech_surface_stalled",
                    },
                )
                self._live_outputs.clear()
                self._idle.set()
                return

    def request_conversation(self, *, input_item_ids: tuple[str, ...], source: SpeechSource) -> bool:
        request = VoiceConversationRequest(input_item_ids)
        if not isinstance(source, SpeechSource) or self._stopping or not self._running:
            return False
        identity = str(uuid.uuid5(uuid.NAMESPACE_URL, f"conversation:{self.conversation_id}:{source.correlation_id}"))
        if identity in self._seen_speech_ids or len(self._seen_speech_ids) >= 4096 or len(self._pending) >= 64:
            return False
        self._seen_speech_ids.add(identity)
        candidate = ConversationCandidate(identity, self.conversation_id, source, request, self.clock.now() + timedelta(seconds=10))
        self._pending.append(candidate)
        self._decision(candidate, SpeechCandidateStatus.DEFERRED, "admitted_input")
        self._note_queued(candidate)
        self._replan()
        self._wakeup.set()
        return candidate in self._pending

    async def _speak_conversation(self, request: ConversationCandidate) -> None:
        if self._stopping or self._eligibility(request)[0] is not SpeechCandidateStatus.ELIGIBLE:
            return
        output_id = str(uuid.uuid4())
        expires = asyncio.get_running_loop().time() + max(0, (request.expires_at - self.clock.now()).total_seconds())
        token = OutputAdmission(expires_at=expires)
        active = _ActiveSpeech(request, output_id, admission=token)
        self._active = active
        self._active_continuation_until = min(
            expires, asyncio.get_running_loop().time() + self.output_timeout_s,
        )
        self._presentation_admissions[output_id] = token
        self._presentation_expiries[output_id] = asyncio.get_running_loop().call_at(expires, self._expire_presentation, active)
        self._live_outputs.add(output_id)
        self._idle.clear()
        queued_at = self._queued_at.pop(request.id, None)
        queue_wait_ms = None if queued_at is None else max(0.0, (self._monotonic() - queued_at) * 1000)
        self._trace(SPEECH_DISPATCHED, "Direct conversation dispatched to frontend", data={
            **self._fields(request), "output_id": output_id,
            "queue_wait_ms": round(queue_wait_ms, 1) if queue_wait_ms is not None else None,
        })
        self._trace("voice.conversation.requested", "Direct conversation generation requested", data={
            **self._fields(request), "output_id": output_id,
        })
        try:
            returned = await self.session.request_conversation(request.request.input_item_ids, source=request.source, output_id=output_id)
            if returned != output_id:
                raise ValueError("reserved conversation output identity changed")
            self._replan()
            self._decision(request, SpeechCandidateStatus.STARTED, "generation_requested")
            await self._await_output(active)
        except asyncio.CancelledError:
            self._invalidate_presentation(active, "start_cancelled")
            raise
        except Exception as exc:
            self._invalidate_presentation(active, "start_failed")
            self._trace(SPEAK_FAILED, "Direct conversation request failed", level="error",
                        data={**self._fields(request), "exception_type": type(exc).__name__, "code": "conversation_request_failed"})
            if self._output_still_alive(output_id):
                await self._await_output(active)
        finally:
            self._active = None
            self._active_continuation_until = None
            handle = self._presentation_expiries.pop(output_id, None)
            if handle is not None:
                handle.cancel()
            if not self._output_still_alive(output_id):
                self._live_outputs.discard(output_id)
                if not self._live_outputs:
                    self._idle.set()
        # Canonical playback ledger alone projects heard text. A generation
        # outcome never manufactures intended text or an assistant history turn.
        self._trace("voice.conversation.finished", "Direct conversation generation released", data={
            **self._fields(request), "output_id": output_id, "generation_status": active.status,
            "interrupted": active.interrupted})

    async def _speak(self, request: SpeechRequest) -> None:
        if isinstance(request, ConversationCandidate):
            await self._speak_conversation(request)
            return
        if self._stopping:
            return
        status, reason = self._eligibility(request)
        if status is not SpeechCandidateStatus.ELIGIBLE:
            self._defer(request, status, reason)
            return
        output_id = str(uuid.uuid4())
        expires = None if request.expires_at is None else asyncio.get_running_loop().time() + max(0, (request.expires_at - self.clock.now()).total_seconds())
        token = OutputAdmission(expires_at=expires)
        active = _ActiveSpeech(request=request, output_id=output_id, admission=token)
        self._active = active  # Own the reservation before any Core/provider await.
        self._active_continuation_until = min(
            expires if expires is not None else float("inf"),
            asyncio.get_running_loop().time() + self.output_timeout_s,
        )
        self._attempted_ids.add(request.id)
        self._presentation_admissions[output_id] = token
        if expires is not None:
            self._presentation_expiries[output_id] = asyncio.get_running_loop().call_at(expires, self._expire_presentation, active)
        self._live_outputs.add(output_id)
        self._idle.clear()
        speak_failed = False
        # Span rule: this invocation closes the mouth span only if it recorded
        # `mouth.speech.started`. A close without an open would render as an
        # `interrupted`/`completed` item carrying text the user never heard.
        started_recorded = False
        try:
            queued_at = self._queued_at.pop(request.id, None)
            queue_wait_ms = (None if queued_at is None else
                             max(0.0, (self._monotonic() - queued_at) * 1000))
            self._trace(SPEECH_DISPATCHED, "Speech dispatched to frontend", data={
                **self._fields(request), "output_id": output_id,
                "queue_wait_ms": round(queue_wait_ms, 1) if queue_wait_ms is not None else None,
            })
            returned = await self.session.speak_reserved(request, output_id=output_id)
            if returned != output_id:
                raise ValueError("Reserved output identity changed")
            self._replan()
            if token.state is not OutputAdmissionState.INVALIDATED:
                self._decision(request, SpeechCandidateStatus.STARTED, "generation_requested")
                started_ref = self._mouth_event(_T.MOUTH_SPEECH_STARTED, request, SPEECH_STARTED, output_id=output_id)
                started_recorded = bool(started_ref)
                self._trace(SPEECH_STARTED, "Speech generation requested", data={
                    **self._fields(request), "output_id": output_id, **started_ref})
            await self._await_output(active)
        except asyncio.CancelledError:
            self._invalidate_presentation(active, "start_cancelled")
            # The tail below never runs: without this close a speech playing when
            # the voice goes to background (mute, idle timeout, shutdown) would
            # stay `open` forever. No journal line follows, hence no trace_ref.
            # One close per span: the tail and the failed branch are skipped.
            # Cancelled before the start was recorded (during `speak_reserved`,
            # or admission already invalidated): no span, nothing to close.
            if started_recorded:
                self._mouth_event(
                    _T.MOUTH_SPEECH_INTERRUPTED, request, None, output_id=output_id, status=active.status,
                    played_ms=active.played_ms if active.interrupted else None,
                    reason="voice_background" if self._stopping else "delivery_cancelled")
            raise
        except Exception as exc:
            self._invalidate_presentation(active, "start_failed")
            speak_failed = True
            self._trace(SPEAK_FAILED, "Speech request failed", level="error",
                        data={**self._fields(request), "code": "speech_speak_failed", "exception_type": type(exc).__name__,
                              # Kept without a recorded start (diagnostic evidence that this speech
                              # was never played), but then without its text.
                              **self._mouth_event(_T.MOUTH_SPEECH_FAILED, request, SPEAK_FAILED, output_id=output_id,
                                                  code="speech_speak_failed", error_class=type(exc).__name__,
                                                  with_content=False)})
            # Failed commands can still have created an output; retain the fence.
            if self._output_still_alive(output_id):
                await self._await_output(active)
        finally:
            self._active = None
            self._active_continuation_until = None
            handle = self._presentation_expiries.pop(output_id, None)
            if handle is not None:
                handle.cancel()
            if not self._output_still_alive(output_id):
                self._live_outputs.discard(output_id)
                if not self._live_outputs:
                    self._idle.set()
        candidate = self._candidates.get(request.id)
        if active.interrupted or active.status != "completed" or token.state is OutputAdmissionState.INVALIDATED:
            if candidate is not None:
                self._blocked_chains.add(candidate.chunk.chain_id)
            self._decision(request, SpeechCandidateStatus.INTERRUPTED, "delivery_not_complete")
            self._replan()
            # A failed start already closed the span (`mouth.speech.failed`): one close per span.
            interrupted_ref = {} if speak_failed or not started_recorded else self._mouth_event(
                _T.MOUTH_SPEECH_INTERRUPTED, request, SPEECH_INTERRUPTED, output_id=output_id, status=active.status,
                played_ms=active.played_ms, reason="user_barge_in" if active.interrupted else "delivery_not_complete")
            self._trace(SPEECH_INTERRUPTED, "Speech interrupted", level="warning", data={**self._fields(request),
                        "output_id": output_id, "status": active.status, "played_ms": active.played_ms,
                        **interrupted_ref})
            if active.interrupted and active.played_ms > 0:
                await self._persist(request, output_id=output_id, played_ms=active.played_ms)
            return
        self._decision(request, SpeechCandidateStatus.COMPLETED, "output_completed")
        if candidate is not None:
            self._chain_next[candidate.chunk.chain_id] = candidate.chunk.index + 1
        self._trace(SPEECH_COMPLETED, "Speech completed", data={
            **self._fields(request), "output_id": output_id,
            **(self._mouth_event(_T.MOUTH_SPEECH_COMPLETED, request, SPEECH_COMPLETED, output_id=output_id)
               if started_recorded else {})})
        await self._persist(request, output_id=output_id)
        self._replan()

    async def _await_output(self, active: _ActiveSpeech) -> None:
        """Attendre la fin de la sortie, en interrogeant l'adaptateur si elle traîne.

        Le délai n'est pas une échéance : c'est un intervalle de vérification.
        Seule la comptabilité de la session peut dire qu'une sortie est finie,
        et l'inventer ferait partir la parole suivante sur une réponse encore
        vivante — l'erreur `conversation_already_has_active_response`.
        """

        while True:
            try:
                await asyncio.wait_for(active.done.wait(), timeout=self.output_timeout_s)
                return
            except asyncio.TimeoutError:
                still_active = self._output_still_alive(active.output_id)
                self._trace(
                    OUTPUT_STALLED,
                    "Aucune fin de sortie reçue dans le délai",
                    level="warning",
                    data={
                        **self._fields(active.request),
                        "output_id": active.output_id,
                        "still_active": bool(still_active),
                        "code": "speech_output_stalled",
                    },
                )
                if still_active:
                    continue
                self._live_outputs.discard(active.output_id)
                if not self._live_outputs:
                    self._idle.set()
                return

    async def _persist(self, request: SpeechRequest, *, output_id: str, played_ms: int | None = None) -> None:
        """Écrire le tour assistant réellement prononcé, avec sa provenance.

        Spec section 15 : c'est l'API de tour normale qui est réutilisée, pas un
        second magasin de transcript. Le texte persisté est celui du cerveau —
        la surface s'est engagée à le restituer mot pour mot (Décision 13) —, et
        le bridge n'écrit rien pour cette réponse-là, sinon le même tour serait
        persisté deux fois, une fois `surface.reflex` et une fois `brain.speech`.

        `played_ms` marque une phrase coupée en cours de route. Le texte reste
        entier — la surface n'a pas le droit de le réécrire, et personne ne sait
        où le couper mot à mot —, mais la métadonnée dit qu'il n'a pas été
        entendu jusqu'au bout. C'est elle qui tient le critère d'acceptation 2 :
        Core ne compte pas une phrase partielle parmi les faits que
        l'utilisateur connaît.
        """

        if getattr(self.session, "canonical_history", False):
            # Task05: Core ledger owns heard history. Provider-generated text
            # and local playback evidence replace the old intended-text claim.
            return
        metadata: dict[str, object] = {
            "provenance": SpeechProvenance.BRAIN.value,
            "speech_id": request.id,
            "work_id": request.work_id,
            "speech_kind": request.kind.value,
            "priority": request.priority.label,
            "output_id": output_id,
        }
        if played_ms is not None:
            metadata["delivery"] = SPEECH_DELIVERY_PARTIAL
            metadata["played_ms"] = played_ms
        try:
            await self.core.append_turn(
                self.conversation_id,
                kind="assistant",
                content=request.text,
                correlation_id=request.correlation_id,
                metadata=metadata,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # L'utilisateur a entendu la phrase : ne pas pouvoir l'archiver est
            # une perte de mémoire, pas une panne de la voix. On continue.
            self._trace(
                PERSIST_FAILED,
                f"Tour assistant cerveau non persisté: {type(exc).__name__}: {exc}",
                level="error",
                data={**self._fields(request), "code": "speech_turn_persist_failed"},
            )

    # -- outillage ----------------------------------------------------------

    def _note_queued(self, request: SpeechRequest) -> None:
        self._queued_at[request.id] = self._monotonic()
        self._trace(SPEECH_QUEUED, "Speech queued", data={
            **self._fields(request), **self._mouth_event(_T.MOUTH_SPEECH_QUEUED, request, SPEECH_QUEUED)})

    # -- Conversation Events (Slice 03b) -------------------------------------

    @staticmethod
    def _remember(memory: OrderedDict, key: str, value: object) -> None:
        memory[key] = value
        memory.move_to_end(key)
        while len(memory) > MAX_MOUTH_EVENT_MEMORY:
            memory.popitem(last=False)

    def _mouth_event(self, event_type: ConversationEventType, request: SpeechRequest | ConversationCandidate,
                     journal_kind: str | None, *, output_id: str | None = None, reason: str | None = None,
                     status: str | None = None, played_ms: int | None = None, code: str | None = None,
                     error_class: str | None = None, with_content: bool = True) -> dict[str, object]:
        """Record one mouth speech fact; return the journal `data` entry that joins it.

        Synchronous and bounded: `record()` only validates and queues. Direct
        conversation candidates carry no speech text nor Core speech request:
        they are not mouth speech events (documented limit).
        """

        recorder = self.conversation_events
        if recorder is None or not isinstance(request, SpeechRequest):
            return {}
        try:
            now = self.clock.now()
            speech_id = request.id
            candidate = self._candidates.get(speech_id)
            chain_id = candidate.chunk.chain_id if candidate is not None else speech_id
            parent = (recorder.derive_event_id(_T.BRAIN_SPEECH_REQUESTED, producer=PRODUCER_BRAIN_SERVICE,
                                               conversation_id=request.conversation_id, source_ids=(chain_id,))
                      if chain_id in self._core_speech_ids else None)
            attributes: dict[str, object] = {"kind": request.kind.value, "priority": request.priority.label}
            if output_id is not None:
                attributes["output_id"] = output_id
            for key, value in (("reason", reason), ("status", status), ("code", code), ("error_class", error_class)):
                token = safe_error_class(value)
                if token is not None:
                    attributes[key] = token
            if played_ms is not None:
                attributes["played_ms"] = int(played_ms)
            fields: dict[str, object] = {
                "session_id": optional_id(str(getattr(self.session, "session_id", "")) or None),
                "correlation_id": request.correlation_id, "speech_id": speech_id,
                "work_id": optional_id(request.work_id), "parent_event_id": parent,
                "trace_ref": journal_trace(journal_kind) if journal_kind else None, "attributes": attributes,
            }
            shape = event_shape(event_type)
            started_at = self._mouth_started.get(speech_id)
            if shape is not EventShape.INSTANT:
                fields["span_id"] = speech_id
            if with_content and (shape is EventShape.SPAN_OPEN
                                 or (shape is EventShape.SPAN_CLOSE and started_at is None)):
                # The text sent for playback, once per span: on the open, or on a
                # close whose speech never started (what was withheld).
                fields["content"] = public_text(request.text)
            if shape is EventShape.SPAN_CLOSE and started_at is not None and started_at <= now:
                fields["started_at"] = started_at
            event_id = recorder.record(event_type, producer=PRODUCER_SPEECH_SCHEDULER,
                                       conversation_id=request.conversation_id, source_ids=(speech_id,),
                                       occurred_at=now, **fields)
            if event_id is not None and shape is EventShape.SPAN_OPEN:
                self._remember(self._mouth_started, speech_id, now)
            return journal_ref(event_id)
        except Exception as exc:  # noqa: BLE001 - instrumentation never changes speech delivery
            self._trace(PRODUCER_FAILED, "Conversation event not recorded", level="warning",
                        data={"conversation_id": self.conversation_id, "event_type": event_type.value,
                              "exception_type": type(exc).__name__})
            return {}

    def _reflex_event(self, reflex: _Reflex, output_id: str) -> dict[str, object]:
        recorder = self.conversation_events
        if recorder is None:
            return {}
        try:
            event_id = recorder.record(
                _T.MOUTH_REFLEX_STARTED, producer=PRODUCER_SPEECH_SCHEDULER, conversation_id=self.conversation_id,
                source_ids=(reflex.correlation_id, output_id), occurred_at=self.clock.now(),
                session_id=optional_id(str(getattr(self.session, "session_id", "")) or None),
                correlation_id=reflex.correlation_id, trace_ref=journal_trace(REFLEX_STARTED),
                attributes={"output_id": output_id})
            return journal_ref(event_id)
        except Exception as exc:  # noqa: BLE001 - instrumentation never changes speech delivery
            self._trace(PRODUCER_FAILED, "Conversation event not recorded", level="warning",
                        data={"conversation_id": self.conversation_id, "event_type": _T.MOUTH_REFLEX_STARTED.value,
                              "exception_type": type(exc).__name__})
            return {}

    def _fields(self, request: SpeechRequest) -> dict[str, object]:
        session_id = str(getattr(self.session, "session_id", "")) or None
        if isinstance(request, ConversationCandidate):
            return {"conversation_id": request.conversation_id, "candidate_id": request.id,
                    "correlation_id": request.correlation_id, "kind": "conversation",
                    "intent_id": request.source.intent_id, "intent_epoch": request.source.intent_epoch,
                    "session_id": session_id}
        return {
            "conversation_id": request.conversation_id,
            "session_id": session_id,
            "speech_id": request.id,
            "correlation_id": request.correlation_id,
            "work_id": request.work_id,
            "kind": request.kind.value,
            "priority": request.priority.label,
        }

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, object] | None = None) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=data)
