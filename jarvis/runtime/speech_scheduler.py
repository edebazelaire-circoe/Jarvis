from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from jarvis.core.latency import FIRST_BRAIN_AUDIO as LATENCY_FIRST_BRAIN_AUDIO, LatencyTracker
from jarvis.core.v2_services import SystemClock
from jarvis.domain.v2 import (
    SPEECH_DELIVERY_PARTIAL,
    TRANSIENT_SPEECH_KINDS,
    PlaybackCursor,
    ProtocolEnvelope,
    SpeechProvenance,
    SpeechRequest,
)
from jarvis.ports.v2 import Clock, RealtimeOutputControl
from jarvis.runtime.journal import RuntimeJournal

# Types d'événements Core consommés ici. Ils sont repris de `brain_service`
# sous forme de littéraux : le runtime ne doit pas importer `jarvis.core`
# pour connaître un nom de canal, et le contrat de transport est
# `docs/handoff-realtime-brain/docs/05-event-contracts.md`, pas un module.
BRAIN_SPEECH_REQUESTED = "brain.speech.requested"
BRAIN_TURN_ACCEPTED = "brain.turn.accepted"
BRAIN_STATE_UPDATED = "brain.state.updated"
BRAIN_INTENT_REVISED = "brain.intent.revised"
BRAIN_EVENT_PREFIX = "brain."

# Télémétrie de livraison (docs/05, section « Voice delivery telemetry »).
# Journal local uniquement : Core n'a pas besoin de savoir ce que le
# haut-parleur a fait, et la Décision 27 dit que `RuntimeJournal` est le
# support d'observabilité de ce dépôt.
SPEECH_QUEUED = "voice.speech.queued"
SPEECH_STARTED = "voice.speech.started"
SPEECH_COMPLETED = "voice.speech.completed"
SPEECH_INTERRUPTED = "voice.speech.interrupted"
SPEECH_EXPIRED = "voice.speech.expired"
SPEECH_SUPERSEDED = "voice.speech.superseded"
SPEECH_IGNORED = "voice.speech.ignored"

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

    request: SpeechRequest
    output_id: str
    done: asyncio.Event = field(default_factory=asyncio.Event)
    status: str = ""
    # Coupée par la parole de l'utilisateur, et ce qui en a été entendu. Le
    # statut du fournisseur ne suffit pas : `cancelled` peut aussi venir d'un
    # échec, et lui seul ne dit pas combien de millisecondes ont été jouées.
    interrupted: bool = False
    played_ms: int = 0


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
    ) -> None:
        self.core = core
        self.conversation_id = conversation_id
        self.session = session
        self.journal = journal
        self.clock = clock or SystemClock()
        self.on_brain_activity = on_brain_activity
        self.output_timeout_s = self.OUTPUT_TIMEOUT_S if output_timeout_s is None else output_timeout_s
        self.reconnect_delay_s = self.RECONNECT_DELAY_S if reconnect_delay_s is None else reconnect_delay_s
        self.transient_ttl_s = self.TRANSIENT_TTL_S if transient_ttl_s is None else transient_ttl_s

        self._pending: list[SpeechRequest] = []
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

    # -- cycle de vie -------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def start(self) -> None:
        """Démarrer l'abonnement et la boucle de livraison."""

        if self._running:
            return
        self._running = True
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
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            if task is not asyncio.current_task():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._expire_all(reason="voice_background")
        self._active = None
        self._live_outputs.clear()
        self._seen_speech_ids.clear()
        self._idle.set()

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
                    "speech_id": speech_id or None,
                    "output_id": output_id or None,
                    "correlation_id": active.request.correlation_id if active is not None else None,
                    "work_id": active.request.work_id if active is not None else None,
                    "kind": active.request.kind.value if active is not None else None,
                },
            )
            return
        if event.message_type == "realtime.output_started":
            if output_id:
                self._live_outputs.add(output_id)
                self._idle.clear()
            return
        if event.message_type != "realtime.response_done":
            return
        status = str(payload.get("status") or "")
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
                stream = self.core.events()
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
            await self._close_stream(stream)
            # Décision 31 : pas de rejeu. Ce qui a été manqué est perdu, donc
            # ce qui reste en file et n'est plus forcément vrai est jeté.
            self._drop_transient(reason="stream_gap")
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

        message_type = envelope.message_type
        if not message_type.startswith(BRAIN_EVENT_PREFIX):
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
        await self._rearm_activity()

        if message_type == BRAIN_SPEECH_REQUESTED:
            request = self._read_request(payload)
            if request is not None:
                # Borne de départ de la mesure 3, posée avant la mise en file :
                # l'attente du silence et le tri des demandes font partie du
                # délai que l'utilisateur subit, ils ne s'en retranchent pas.
                self._latency.mark(LATENCY_FIRST_BRAIN_AUDIO, request.id)
                self._enqueue(request)
        elif message_type == BRAIN_TURN_ACCEPTED:
            self._note_revision(payload.get("revision"))
            # Un nouveau tour utilisateur faisant autorité est une révision
            # d'intention : ce qui attendait d'être dit sur l'intention
            # précédente ne l'est plus (spec section 6).
            self._drop_transient(reason="intent_revised")
        elif message_type == BRAIN_INTENT_REVISED:
            self._note_revision(payload.get("revision"))
            # Core a désigné le travail dont la parole n'est plus vraie. C'est
            # une décision du cerveau, pas une heuristique de surface : elle
            # emporte donc aussi les paroles durables (résultat, question), que
            # rien d'autre ne permet de retirer (Décision 14). Le travail
            # `retained` n'est jamais touché.
            self._drop_work(payload.get("superseded_work_ids"), reason="work_superseded")
            self._drop_work(payload.get("cancelled_work_ids"), reason="work_cancelled")
            self._drop_transient(reason="intent_revised")
        elif message_type == BRAIN_STATE_UPDATED:
            self._note_revision(payload.get("revision"))
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

    def _enqueue(self, request: SpeechRequest) -> None:
        if request.id in self._seen_speech_ids:
            self._trace(
                SPEECH_IGNORED,
                request.text[:300],
                data={**self._fields(request), "reason": "duplicate_speech_id"},
            )
            return
        self._seen_speech_ids.add(request.id)
        if request.conversation_id != self.conversation_id:
            self._trace(
                SPEECH_IGNORED,
                request.text[:300],
                data={**self._fields(request), "reason": "other_conversation"},
            )
            return
        now = self.clock.now()
        if request.is_expired(now):
            self._trace(SPEECH_EXPIRED, request.text[:300], data={**self._fields(request), "reason": "ttl"})
            return
        # Relation dirigée : une demande peut arriver déjà périmée par ce qui
        # est en file (ordre d'arrivée non garanti), et inversement.
        for queued in tuple(self._pending):
            if queued.supersedes(request):
                self._trace(
                    SPEECH_SUPERSEDED,
                    request.text[:300],
                    data={**self._fields(request), "reason": "superseded_on_arrival", "by_speech_id": queued.id},
                )
                return
        for queued in tuple(self._pending):
            if request.supersedes(queued):
                self._pending.remove(queued)
                self._trace(
                    SPEECH_SUPERSEDED,
                    queued.text[:300],
                    data={**self._fields(queued), "reason": "superseded", "by_speech_id": request.id},
                )
        self._pending.append(request)
        self._trace(SPEECH_QUEUED, request.text[:300], data=self._fields(request))
        self._wakeup.set()

    def _drop_work(self, raw: object, *, reason: str) -> None:
        """Jeter la parole en file rattachée à des travaux désignés par Core.

        Ne touche que la file : une sortie déjà commencée relève de la séquence
        de barge-in, pas de l'ordonnancement. Une charge utile mal formée est
        ignorée sans bruit ici — `_note_revision` a déjà vu la révision, et
        refuser l'évènement entier pour un champ absent priverait la surface de
        l'invalidation qu'il portait.
        """

        if not isinstance(raw, (list, tuple, set)):
            return
        work_ids = {str(value) for value in raw if value}
        if not work_ids:
            return
        for queued in tuple(self._pending):
            if queued.work_id in work_ids:
                self._pending.remove(queued)
                self._trace(SPEECH_SUPERSEDED, queued.text[:300], data={**self._fields(queued), "reason": reason})

    def _drop_transient(self, *, reason: str) -> None:
        """Jeter la parole transitoire que l'évènement courant rend caduque."""

        for queued in tuple(self._pending):
            if queued.kind in TRANSIENT_KINDS:
                self._pending.remove(queued)
                self._trace(SPEECH_SUPERSEDED, queued.text[:300], data={**self._fields(queued), "reason": reason})

    def _expire_all(self, *, reason: str) -> None:
        for queued in tuple(self._pending):
            self._trace(SPEECH_EXPIRED, queued.text[:300], data={**self._fields(queued), "reason": reason})
        self._pending.clear()

    def _pop_next(self) -> SpeechRequest | None:
        """Retirer la demande à dire maintenant : priorité, puis FIFO."""

        now = self.clock.now()
        for queued in tuple(self._pending):
            if queued.is_expired(now):
                self._pending.remove(queued)
                self._trace(SPEECH_EXPIRED, queued.text[:300], data={**self._fields(queued), "reason": "ttl"})
        if not self._pending:
            return None
        chosen = min(self._pending, key=lambda item: item.ordering_key)
        self._pending.remove(chosen)
        return chosen

    # -- livraison ----------------------------------------------------------

    async def _deliver_pending(self) -> None:
        """Boucle de livraison : seule voie d'accès à `speak()`."""

        while True:
            await self._wakeup.wait()
            self._wakeup.clear()
            while self._pending:
                # Attendre le silence **avant** de choisir : une attente longue
                # peut voir arriver un résultat qui périme la progression qu'on
                # aurait sinon déjà retirée de la file.
                await self._wait_until_silent()
                request = self._pop_next()
                if request is None:
                    break
                await self._speak(request)

    async def _wait_until_silent(self) -> None:
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
                if getattr(self.session, "active_output_id", None) is not None:
                    continue
                self._trace(
                    OUTPUT_STALLED,
                    "Sortie vocale sans fin annoncée : la file de parole est débloquée",
                    level="warning",
                    data={
                        "conversation_id": self.conversation_id,
                        "live_outputs": sorted(self._live_outputs),
                        "code": "speech_surface_stalled",
                    },
                )
                self._live_outputs.clear()
                self._idle.set()
                return

    async def _speak(self, request: SpeechRequest) -> None:
        try:
            output_id = await self.session.speak(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._trace(
                SPEAK_FAILED,
                f"La surface n'a pas pu prononcer la demande: {type(exc).__name__}: {exc}",
                level="error",
                data={**self._fields(request), "code": "speech_speak_failed"},
            )
            return
        active = _ActiveSpeech(request=request, output_id=str(output_id))
        self._active = active
        # Le fournisseur n'a pas encore confirmé la création de la réponse :
        # marquer la sortie tout de suite est ce qui empêche un second
        # `speak()` de partir dans cet intervalle.
        self._live_outputs.add(active.output_id)
        self._idle.clear()
        self._trace(SPEECH_STARTED, request.text[:300], data={**self._fields(request), "output_id": active.output_id})
        try:
            await self._await_output(active)
        finally:
            self._active = None
        if active.interrupted or (active.status and active.status != "completed"):
            self._trace(
                SPEECH_INTERRUPTED,
                request.text[:300],
                level="warning",
                data={
                    **self._fields(request),
                    "output_id": active.output_id,
                    "status": active.status,
                    "played_ms": active.played_ms,
                },
            )
            # Ce qui n'a jamais atteint le haut-parleur n'appartient pas à
            # l'historique : une sortie refusée par le fournisseur, ou coupée
            # avant le premier bloc audio, n'a rien à y laisser. Une phrase
            # entamée, si : la taire ferait croire au cerveau qu'il n'a rien dit
            # et il la redirait en entier.
            if active.interrupted and active.played_ms > 0:
                await self._persist(request, output_id=active.output_id, played_ms=active.played_ms)
            return
        self._trace(SPEECH_COMPLETED, request.text[:300], data={**self._fields(request), "output_id": active.output_id})
        await self._persist(request, output_id=active.output_id)

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
                still_active = getattr(self.session, "active_output_id", None) == active.output_id
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

    def _fields(self, request: SpeechRequest) -> dict[str, object]:
        return {
            "conversation_id": request.conversation_id,
            "speech_id": request.id,
            "correlation_id": request.correlation_id,
            "work_id": request.work_id,
            "kind": request.kind.value,
            "priority": request.priority.label,
        }

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, object] | None = None) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=data)
