from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from jarvis.core.v2_services import SystemClock
from jarvis.domain.errors import ConfigurationError
from jarvis.domain.speaker import (
    AuthorizationStatus,
    ConversationAuthorization,
    ConversationAuthorizationError,
    VerifierAvailability,
    assess_authorization,
)
from jarvis.domain.v2 import AddressingDecision, VoiceLifecycleState
from jarvis.domain.voice_frontend import FrontendState, VoiceOperationResult, VoiceOperationStatus
from jarvis.ports.v2 import Clock, RealtimeSession, WakeWordBackend, supports_output_control
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.interaction_mode_observer import InteractionModeObserver
from jarvis.runtime.speech_scheduler import SpeechScheduler
from jarvis.runtime.visual_signals import VisualSignalBus
from jarvis.v2_config import VoiceArchitecture


class UsefulActivityTracker:
    """Délai d'activité utile d'une session ACTIVE.

    `timeout_s <= 0` désactive le délai : la session ne rend alors la main que
    sur la touche de réveil, un mute vocal ou une panne irrécupérable.
    """

    def __init__(self, *, timeout_s: float, clock: Clock | None = None) -> None:
        self.timeout_s = timeout_s
        self.clock = clock or SystemClock()
        self._last_useful = self.clock.now()

    @property
    def enabled(self) -> bool:
        return self.timeout_s > 0

    def reset(self, decision: AddressingDecision = AddressingDecision.ADDRESSED) -> None:
        if decision is AddressingDecision.ADDRESSED:
            self._last_useful = self.clock.now()

    def expired(self) -> bool:
        if not self.enabled:
            return False
        return (self.clock.now() - self._last_useful).total_seconds() >= self.timeout_s

    def remaining_seconds(self) -> float | None:
        if not self.enabled:
            return None
        elapsed = (self.clock.now() - self._last_useful).total_seconds()
        return max(0.0, self.timeout_s - elapsed)


@dataclass(slots=True)
class VoiceRuntimeState:
    state: VoiceLifecycleState = VoiceLifecycleState.BACKGROUND
    conversation_id: str | None = None


class PersistentVoiceRuntime:
    """Wake/background lifecycle. Core is never stopped by mute or inactivity.

    Deux architectures cohabitent, choisies par `voice_arch` (Décision 20) :

    - `LEGACY` : un appui de réveil, un tour, retour au fond dès que la réponse
      est terminée. Le micro est fermé au moment où le fournisseur clôt le tour,
      donc les haut-parleurs ne peuvent jamais nourrir le VAD suivant.
    - `CONTINUOUS_BRAIN` : une session ACTIVE couvre plusieurs tours. Seuls un
      mute explicite (touche de réveil ou « Jarvis mute »), le délai d'activité
      utile — sauf s'il vaut 0 — ou une panne irrécupérable ramènent au fond (Décisions 08 et 09). Le micro reste ouvert entre les
      tours ; l'écho acoustique (spec §11) est traité par la capture duplex
      que fournit `capture_factory` (`jarvis/audio/duplex.py`). `LEGACY`
      reste le repli half-duplex.

    Écouter, parler et travailler restent des projections d'activité : elles ne
    sont jamais encodées comme des états de `VoiceLifecycleState`.
    """

    def __init__(
        self,
        *,
        wakeword: WakeWordBackend,
        core: LocalCoreClient,
        realtime_factory: Callable[[dict[str, object]], Awaitable[RealtimeSession]],
        active_timeout_s: float = 90.0,
        clock: Clock | None = None,
        signals: VisualSignalBus | None = None,
        journal: RuntimeJournal | None = None,
        audio_input_device: int | str | None = None,
        audio_output_device: int | str | None = None,
        auto_turn: bool = False,
        claude=None,
        input_sample_rate: int = 24000,
        output_sample_rate: int = 24000,
        voice_arch: VoiceArchitecture = VoiceArchitecture.LEGACY,
        capture_factory: Callable[[], object] | None = None,
        reflex_delay_s: float = 0.0,
        reflex_require_work: bool = False,
        engagement_window_s: float = 30.0,
        authorization: ConversationAuthorization | None = None,
        authorization_error: ConversationAuthorizationError | None = None,
        echo_cancellation: bool | None = None,
        conversation_architecture=None,
        conversation_model: str | None = None,
        configuration_id: str | None = None,
        initial_conversation_id: str | None = None,
        switch_handoff: dict[str, object] | None = None,
        switch_bus=None,
        metric_recorder_factory: Callable[[], object] | None = None,
        conversation_events=None,
    ) -> None:
        self.voice_arch = voice_arch
        # Mode d'interaction (Slice 02) : ce que Core dit du mode effectif.
        # Vit avec le **processus**, pas avec une session : une activation ne
        # doit pas réinitialiser ce que Core a déjà annoncé. Décision D15 : le
        # mode n'entre pas dans `configuration_id`, donc en changer ne
        # redémarre rien ici et ne coupe aucune audio.
        self.interaction_mode = InteractionModeObserver(journal=journal)
        # Conversation Events (Slice 03b) : l'enregistreur borné du processus
        # (`ConversationEventForwarder`), transmis à chaque ordonnanceur et bridge.
        # Sa vie est celle du processus Voice, pas celle d'une activation.
        self.conversation_events = conversation_events
        from jarvis.domain.voice_architecture import VoiceArchitectureId
        if conversation_architecture not in (None, VoiceArchitectureId.SIMPLE, VoiceArchitectureId.FRONT_BRAIN, VoiceArchitectureId.DUPLEX):
            raise ConfigurationError("Unsupported conversational voice architecture")
        self.conversation_architecture = conversation_architecture
        self.conversation_model = conversation_model
        self.configuration_id = configuration_id
        self.switch_handoff = switch_handoff
        self.switch_bus = switch_bus
        self.metric_recorder_factory = metric_recorder_factory
        self._metrics = None
        self._metric_live_record = None
        # Annulation d'écho demandée par les réglages de la pile (mode continu),
        # ou None si inconnu : sert seulement à dire au Control Center ce qui
        # a été demandé face à ce que la capture applique (tâche 08).
        self.echo_cancellation = echo_cancellation
        self._aec_failure_traced = False
        # Qui peut parler à JARVIS (`conversation_mode`, domaine `speaker`).
        # Absent : salle ouverte, le comportement d'avant ce réglage.
        self.authorization = authorization or ConversationAuthorization()
        # Réglage d'autorisation illisible (fichier écrit à la main) : Voice
        # ne devine pas ce qui était voulu — elle refuse d'écouter et le dit
        # à chaque réveil (tâche 07), au lieu de retomber sur la salle ouverte.
        self.authorization_error = authorization_error
        if self.continuous and not auto_turn:
            # Le mode continu est défini par le découpage des tours côté
            # fournisseur : c'est lui qui permet de garder le micro ouvert d'un
            # bout à l'autre de la session. En mode manuel, un tour se termine
            # par une fermeture du flux d'entrée, et enchaîner demanderait de
            # rouvrir PortAudio à chaque tour — précisément la manœuvre que la
            # séquence d'extinction actuelle rend risquée. On refuse au lieu de
            # dégrader en silence.
            raise ConfigurationError(
                "JARVIS_VOICE_ARCH=continuous_brain exige le mode de tour automatique. "
                "Remettez « Fin de tour » sur « auto » dans les réglages du Control Center, "
                "ou repassez JARVIS_VOICE_ARCH sur 'legacy'."
            )
        self.wakeword = wakeword
        self.core = core
        self.realtime_factory = realtime_factory
        self.clock = clock or SystemClock()
        self.activity = UsefulActivityTracker(timeout_s=active_timeout_s, clock=self.clock)
        self.runtime = VoiceRuntimeState(conversation_id=initial_conversation_id)
        self.signals = signals
        self.journal = journal
        self.audio_input_device = audio_input_device
        self.audio_output_device = audio_output_device
        self.auto_turn = auto_turn
        # Fréquences imposées par la pile vocale choisie : OpenAI Realtime veut
        # 24 kHz dans les deux sens, Gemini Live 16 kHz en entrée et 24 en sortie.
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        # Passerelle vers l'agent Claude local, chemin legacy uniquement : en
        # mode continu, l'agent est joint par Core à travers un `BrainBackend`,
        # et cette passerelle n'est transmise à aucun bridge (Décisions 19 et 23).
        self.claude = claude
        # Mode continu : traitement duplex du micro (annulation d'écho, garde
        # d'écho). Fourni par le composition root, qui connaît l'adaptateur ;
        # créé une fois et gardé d'une session à l'autre pour ne pas
        # réapprendre la pièce à chaque réveil. Absent : micro brut.
        self.capture_factory = capture_factory
        self._capture: object | None = None
        # Délai laissé au cerveau avant que la surface n'accuse réception
        # (0 = jamais), et fenêtre de conversation pour l'adressage.
        self.reflex_delay_s = reflex_delay_s
        self.reflex_require_work = reflex_require_work
        self.engagement_window_s = engagement_window_s
        self._session: RealtimeSession | None = None
        self._pending_canonical_close: RealtimeSession | None = None
        self._pending_audio = None
        self._mute_task: asyncio.Task | None = None
        self._bridge = None
        self._bridge_task: asyncio.Task[None] | None = None
        # Ordonnanceur de la parole du cerveau. Sa durée de vie est celle du
        # transport vocal ACTIF, pas celle du travail : il naît avec la session
        # et meurt au mute, tandis que le travail continue dans Core.
        self._speech: SpeechScheduler | None = None
        self._turn_submitted = False
        # Fait d'écran, indépendant de la bouche : le cerveau a reçu un tour
        # adressé et n'a pas encore ouvert la bouche. Voir `_displayed`.
        self._brain_working = False
        # Second fait d'écran, tenu par l'ordonnanceur de parole : Core a un
        # travail du cerveau en cours pour cette conversation. Voir `brain_work`.
        self._brain_busy = False
        # Délai de grâce d'un `brain_pending` que Core n'a pas (encore) relayé.
        self._brain_pending_expiry: asyncio.Task[None] | None = None
        # Dernier état demandé par la bouche, avant dérivation : il est
        # republié quand l'un des deux faits du cerveau change seul.
        self._requested_visual = "idle"
        self._stop = asyncio.Event()
        self._visual("idle")

    @property
    def continuous(self) -> bool:
        """Vrai quand une session ACTIVE doit couvrir plusieurs tours."""

        return self.conversation_architecture is not None or self.voice_arch is VoiceArchitecture.CONTINUOUS_BRAIN

    def _visual(self, state: str) -> None:
        self._requested_visual = state
        if self.signals is not None:
            self.signals.state(self._displayed(state))

    def _displayed(self, state: str) -> str:
        """Dériver la couleur à partir de deux faits, au lieu d'un seul champ.

        Le bus n'a qu'un état, et jusqu'ici le dernier émetteur l'écrasait :
        la fin de la parole du cerveau réflexe rendait l'écran à l'écoute
        alors que le cerveau principal réfléchissait toujours, et le violet ne
        revenait jamais. Les deux faits sont désormais tenus séparément — le
        cerveau réfléchit (`_brain_working`), quelque chose est en train
        d'être dit (« speaking ») — et la couleur en découle : on parle, donc
        orange ; sinon le cerveau travaille, donc violet ; sinon l'écoute ou
        la veille. L'alternance peut donc se répéter autant de fois qu'il le
        faut, sans rester coincée.

        « Le cerveau réfléchit » a deux sources : le bridge, dès que le tour
        part (`brain_pending`, immédiat), et Core, tant qu'un travail du
        cerveau est ouvert (`brain_work`, relayé par l'ordonnanceur). La
        seconde est la seule à savoir quand il a fini sur tous les chemins.
        """

        if (self._brain_working or self._brain_busy) and state in {"idle", "listening"}:
            return "thinking"
        return state

    #: Un tour annoncé par le bridge que Core ne relaie jamais comme travail
    #: (délégation sans demande lisible, tour refusé) ne doit pas laisser
    #: l'orbe au violet : passé ce délai sans `brain.work.started`, l'annonce
    #: est oubliée. Core accepte un tour en moins d'une seconde.
    BRAIN_PENDING_GRACE_S = 10.0

    async def brain_pending(self, pending: bool) -> None:
        """Le bridge annonce que le cerveau doit encore répondre, ou non.

        Ne publie rien : l'évènement de bouche qui suit (`thinking`,
        `speaking`, retour à l'écoute) portera la couleur dérivée.
        """

        self._brain_working = bool(pending)
        self._cancel_brain_pending_expiry()
        if self._brain_working and self._speech is not None:
            self._brain_pending_expiry = asyncio.create_task(
                self._expire_brain_pending(), name="jarvis-voice-brain-pending-expiry",
            )

    async def brain_work(self, busy: bool) -> None:
        """Core commence ou finit de travailler sur un tour de la conversation.

        Relayé par l'ordonnanceur de parole (`brain.work.*`). Au début, le
        travail prend le relais de l'annonce du bridge. À la fin, les deux
        faits tombent : le tour est rendu, même si aucune parole n'en porte
        la fin — en GPT-Live aucune sortie n'a de `speech_id`, et une tâche
        simple finit sans rien dire. L'écran est republié tout de suite quand
        il montrait l'écoute ou la veille ; une parole en cours reste orange
        et redescendra d'elle-même.
        """

        self._brain_busy = bool(busy)
        self._cancel_brain_pending_expiry()
        if not busy:
            self._brain_working = False
        self._republish_rest()

    async def _expire_brain_pending(self) -> None:
        await asyncio.sleep(self.BRAIN_PENDING_GRACE_S)
        self._brain_pending_expiry = None
        if self._brain_working and not self._brain_busy:
            self._brain_working = False
            self._republish_rest()

    def _republish_rest(self) -> None:
        """Republier l'écoute ou la veille, avec la couleur dérivée à jour.

        « thinking » demandé par la bouche n'a qu'un sens en session active :
        le tour vient de partir au cerveau (`on_thinking` du bridge). Quand le
        cerveau a fini sans qu'une parole ramène l'écoute, c'est l'écoute qui
        revient — l'utilisateur vient de parler à JARVIS.
        """

        if self.runtime.state is not VoiceLifecycleState.ACTIVE:
            return
        requested = self._requested_visual
        if requested == "thinking" and not (self._brain_working or self._brain_busy):
            requested = "listening"
        if requested in {"idle", "listening"}:
            self._visual(requested)

    def _cancel_brain_pending_expiry(self) -> None:
        task, self._brain_pending_expiry = self._brain_pending_expiry, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def _forget_brain_display(self) -> None:
        """La voix repasse au fond : plus aucun tour n'est affiché en cours."""

        self._cancel_brain_pending_expiry()
        self._brain_working = False
        self._brain_busy = False

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, object] | None = None) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=data)

    async def run(self) -> None:
        if self.signals is not None:
            self.signals.heartbeat()
        self._trace("voice.start", "Voice runtime started")
        self._announce_static_refusal()
        detections = self.wakeword.detections()
        detection_task: asyncio.Task[str] | None = None
        stop_task = asyncio.create_task(self._stop.wait(), name="jarvis-voice-stop-wait")
        try:
            while not self._stop.is_set():
                if detection_task is None:
                    detection_task = asyncio.create_task(anext(detections), name="jarvis-manual-toggle")

                if self.runtime.state is VoiceLifecycleState.BACKGROUND:
                    try:
                        done, _ = await asyncio.wait({detection_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
                        if stop_task in done:
                            break
                        keyword = detection_task.result()
                    except StopAsyncIteration:
                        break
                    detection_task = None
                    self._trace("voice.wake", "Wake detected", data={"source": keyword})
                    await self.activate()
                    continue

                bridge_task = self._bridge_task
                if bridge_task is None:
                    await self.mute()
                    # An UNKNOWN provider close is retained for reconciliation.
                    # Do not retry it at scheduler speed while no bridge can
                    # make progress; the durable Live reaper owns recovery.
                    if self._pending_canonical_close is not None:
                        try:
                            await asyncio.wait_for(self._stop.wait(), timeout=.1)
                        except TimeoutError:
                            pass
                    continue

                done, _ = await asyncio.wait({detection_task, bridge_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
                if stop_task in done:
                    break
                if detection_task in done:
                    try:
                        keyword = detection_task.result()
                    except StopAsyncIteration:
                        break
                    detection_task = None
                    if self.runtime.state is VoiceLifecycleState.ACTIVE:
                        # Under server VAD the turn closes on silence, so the wake key
                        # only ever means "stop": there is nothing left to submit.
                        if self._turn_submitted or self.auto_turn:
                            self._trace("voice.manual_cancel", "Manual key cancelled the active response")
                            await self.mute()
                        else:
                            await self.submit_active_turn(source=keyword)
                    continue

                outcome = (await asyncio.gather(bridge_task, return_exceptions=True))[0]
                if self.runtime.state is not VoiceLifecycleState.BACKGROUND:
                    from jarvis.domain.voice_frontend import VoiceStopReason
                    await self.mute(
                        VoiceStopReason.ERROR
                        if isinstance(outcome, BaseException) else VoiceStopReason.USER
                    )
                if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                    self._trace("voice.failure", str(outcome), level="error")
                    raise outcome
        finally:
            if detection_task is not None:
                detection_task.cancel()
                await asyncio.gather(detection_task, return_exceptions=True)
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            await self.close()

    async def activate(self) -> None:
        if self._mute_task is not None and not self._mute_task.done():
            return
        if self._pending_audio is not None:
            if not await self._reconcile_audio_close():
                return  # Never reopen a device still owned by native cleanup.
            self.runtime.state = VoiceLifecycleState.BACKGROUND
        if self._pending_canonical_close is not None:
            if not await self._close_provider_session(self._pending_canonical_close):
                return
            self.runtime.state = VoiceLifecycleState.BACKGROUND
        if self.runtime.state is not VoiceLifecycleState.BACKGROUND:
            return
        capture: object | None = None
        capture_prepared = False
        if self.authorization.owner_enforced or self.authorization_error is not None:
            # Solo Owner (tâche 07) : accepté ou refusé avant d'ouvrir quoi que
            # ce soit — ni session fournisseur, ni micro, ni mot d'éveil
            # suspendu. La capture (et son vérificateur) est préparée d'abord :
            # c'est elle qui dit si la voix du propriétaire peut être reconnue.
            capture = self._duplex_capture() if self.continuous else None
            capture_prepared = True
            refusal = self._authorization_refusal(capture)
            if refusal is not None:
                self._refuse_activation(*refusal, phase="activation")
                return
        self.runtime.state = VoiceLifecycleState.CONNECTING
        self._visual("thinking")
        self._trace("voice.connecting", "Opening Realtime session")
        context = None
        if self.runtime.conversation_id is not None:
            try:
                context = await self.core.context(self.runtime.conversation_id)
            except CoreProtocolError as exc:
                # Pointeur mémorisé (`.voice_conversation`, handoff) vers une
                # conversation que Core ne connaît plus — base restaurée ou
                # réinitialisée. Le 404 est définitif : on repart d'une
                # conversation neuve plutôt que de faire tomber la voix.
                if exc.status != 404:
                    raise
                self._trace("voice.conversation_unknown", "Remembered conversation unknown to Core; starting a new one",
                            level="warning", data={"conversation_id": self.runtime.conversation_id})
                self.runtime.conversation_id = None
        if self.runtime.conversation_id is None:
            conversation = await self.core.create_conversation()
            self.runtime.conversation_id = str(conversation["id"])
            context = await self.core.context(self.runtime.conversation_id)
        if self.switch_bus is not None and self.configuration_id is not None:
            self.switch_bus.remember_conversation(self.runtime.conversation_id, self.configuration_id)
        if self.switch_handoff is not None:
            from jarvis.runtime.voice_switch import active_task_context
            try:
                task_context = active_task_context(await self.core.work_snapshot())
            except Exception as exc:
                task_context = ""
                self._trace("voice.switch.context_degraded", "Active work context unavailable during switch",
                            level="warning", data={"code": "voice_switch_work_unavailable",
                                                   "exception_type": type(exc).__name__})
            if task_context:
                context = {**context, "switch_task_context": task_context}
        try:
            if self.metric_recorder_factory is not None:
                if self._metrics is not None:
                    self._finish_metrics("uncertain")
                if self._metrics is not None:
                    raise RuntimeError("previous voice metric report is still pending")
                self._metrics = self.metric_recorder_factory()
                self._metric_live_record = None
                self._metrics.start(conversation_id=self.runtime.conversation_id)
            self._session = await self.realtime_factory(context)
            if self._metrics is not None:
                self._metrics.identify_frontend(
                    session_id=str(getattr(self._session, "session_id", "unknown")),
                    prompt_applications=getattr(self._session, "prompt_applications", ()),
                )
            attach = getattr(self._session, "attach_core", None)
            if callable(attach):
                await attach(self.core, self.runtime.conversation_id,
                             on_failure=lambda: asyncio.create_task(self._close_failed_evidence(), name="jarvis-voice-evidence-stop"),
                             journal=self.journal)
        except Exception as exc:
            self.runtime.state = VoiceLifecycleState.ERROR
            if self.signals is not None:
                self.signals.alert(str(exc))
            self._trace("voice.provider_error", str(exc), level="error")
            if self._metrics is not None:
                self._finish_metrics("failed")
            if self.switch_handoff is not None and self.switch_bus is not None:
                self.switch_bus.mark_handoff_failed(
                    self.switch_handoff, code=f"replacement_start_failed:{type(exc).__name__}",
                )
                self._trace(
                    "voice.switch.replacement_failed", "Replacement voice frontend failed to start",
                    level="error", data={"code": "voice_switch_replacement_failed",
                                         "exception_type": type(exc).__name__,
                                         "request_id": self.switch_handoff.get("request_id")},
                )
            await self.mute()
            raise
        if self.continuous and not supports_output_control(self._session):
            # Décisions 21 et 22 : le mode continu s'appuie sur les contrôles de
            # sortie sémantiques du port `RealtimeOutputControl`. Une pile qui ne
            # les annonce pas (Gemini Live aujourd'hui) doit échouer bruyamment
            # plutôt que retomber en silence sur l'ancien cycle de vie.
            message = (
                "La pile vocale active ne sait pas piloter la sortie audio "
                f"({type(self._session).__name__} n'implémente pas speak/cancel_output/truncate). "
                "Le mode continu ne peut pas fonctionner sur cette pile : choisissez OpenAI Realtime "
                "dans les réglages du Control Center, ou repassez JARVIS_VOICE_ARCH sur 'legacy'."
            )
            self.runtime.state = VoiceLifecycleState.ERROR
            if self.signals is not None:
                self.signals.alert(message)
            self._trace(
                "voice.arch_unsupported",
                message,
                level="error",
                data={"arch": self.voice_arch.value, "code": "voice_arch_stack_without_output_control"},
            )
            await self.mute()
            raise ConfigurationError(message)
        await self.wakeword.suspend_for_active_session()
        self.activity.reset()
        self._turn_submitted = False
        self._brain_working = False
        self.runtime.state = VoiceLifecycleState.ACTIVE
        if self.signals is not None:
            self.signals.alert(None)
        self._trace(
            "voice.active",
            "Realtime session active",
            data={"conversation_id": self.runtime.conversation_id, "arch": self.conversation_architecture.value if self.conversation_architecture is not None else self.voice_arch.value},
        )
        if self.switch_handoff is not None:
            from jarvis.runtime.voice_switch import prompt_transition_evidence
            prompt_apps = getattr(self._session, "prompt_applications", ())
            evidence = prompt_transition_evidence(prompt_apps)
            self._trace(
                "voice.switch.completed", "Replacement voice frontend is active",
                data={"request_id": self.switch_handoff.get("request_id"),
                      "source_configuration_id": self.switch_handoff.get("source_configuration_id"),
                      "target_configuration_id": self.configuration_id,
                      "source_architecture": self.switch_handoff.get("source_architecture"),
                      "source_model": self.switch_handoff.get("source_model"),
                      "architecture": self.conversation_architecture.value if self.conversation_architecture else self.voice_arch.value,
                      "model": self.conversation_model, "prompt_applications": evidence,
                      "recent_turn_count": self.switch_handoff.get("recent_turn_count"),
                      "active_work_count": self.switch_handoff.get("active_work_count")},
            )
            if self.switch_bus is not None:
                self.switch_bus.clear_handoff(self.switch_handoff.get("request_id"))
            self.switch_handoff = None
        from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
        # Tâche 08 : en mode continu, la parole du cerveau arrive par
        # `/v1/events` et personne d'autre ne la restituerait. L'ordonnanceur
        # est créé avant le bridge parce que celui-ci lui relaie le cycle de
        # vie des sorties vocales.
        speech = (
            SpeechScheduler(
                core=self.core,
                conversation_id=self.runtime.conversation_id,
                session=self._session,  # type: ignore[arg-type]
                journal=self.journal,
                clock=self.clock,
                on_brain_activity=self.brain_activity,
                on_brain_busy=self.brain_work,
                reflex_delay_s=self.reflex_delay_s,
                reflex_require_work=self.reflex_require_work,
                conversation_events=self.conversation_events,
                interaction_mode=self.interaction_mode,
            )
            if self.continuous
            else None
        )
        self._speech = speech
        if speech is not None and hasattr(self._session, "set_back_brain_presenter"):
            self._session.set_back_brain_presenter(speech.enqueue_controller_speech)
        audio_options: dict[str, object] = {}
        if not capture_prepared:
            capture = self._duplex_capture() if self.continuous else None
        if capture is not None:
            audio_options["capture"] = capture
        barge_in_authority, owner_source = self._barge_in_policy(capture)
        if owner_source is not None:
            self._report_authorization("ready", phase="activation")
        bridge = RealtimeConversationBridge(
            core=self.core,
            session=self._session,
            conversation_id=self.runtime.conversation_id,
            audio=SoundDeviceRealtimeAudio(
                input_device=self.audio_input_device,
                output_device=self.audio_output_device,
                input_sample_rate=self.input_sample_rate,
                output_sample_rate=self.output_sample_rate,
                journal=self.journal,
                **audio_options,
            ),
            on_addressed=self.addressed_activity,
            on_ambient=self.ambient_activity,
            on_mute=self.mute,
            on_listening=self.visual_listening,
            # Session ACTIVE mais rien d'adressé : la surface reste en veille
            # au lieu d'annoncer une écoute que l'utilisateur n'a pas demandée.
            on_idle=self.visual_idle,
            on_thinking=self.visual_thinking,
            on_speaking=self.visual_speaking,
            # Décision 08 : en continu, une réponse terminée rouvre l'écoute au
            # lieu de rendre la main au mot d'éveil.
            on_response_done=self.turn_completed if self.continuous else self.mute,
            # Fait tenu à part de la bouche : sans lui, la fin du préambule du
            # cerveau réflexe rendrait l'écran à l'écoute au lieu du violet.
            on_brain_pending=self.brain_pending,
            on_output_event=speech.note_output_event if speech is not None else None,
            # Tâche 09 : le bridge coupe la lecture, l'ordonnanceur sait quelle
            # demande de parole y était rattachée. Sans ce fil, l'historique
            # présenterait comme entendue une phrase tronquée.
            on_interruption=speech.note_interruption if speech is not None else None,
            # 19/09/2026 : couper JARVIS pendant qu'il réfléchit ne coupe aucune
            # phrase — il n'y en a pas. Ce fil-là abandonne le tour : la file de
            # parole est purgée et Core arrête la tâche du cerveau. Ce que le
            # tour avait lancé continue.
            on_turn_abandoned=speech.abandon_turn if speech is not None else None,
            # L'ordonnanceur ne parle pas par-dessus l'utilisateur, et décide
            # seul si un accusé de réception sert encore.
            on_user_speech=speech.note_user_speech if speech is not None else None,
            on_reflex=speech.request_reflex if speech is not None else None,
            output_admission=speech.output_admission if speech is not None else None,
            engagement_window_s=self.engagement_window_s,
            auto_turn=self.auto_turn,
            continuous=self.continuous,
            direct_conversation=self.conversation_architecture is not None,
            on_conversation=speech.request_conversation if self.conversation_architecture is not None and speech is not None else None,
            journal=self.journal,
            # Solo Owner (tâche 05) : qui a le droit de couper JARVIS.
            barge_in_authority=barge_in_authority,
            owner_source=owner_source,
            # Tâche 07 : vérificateur perdu en cours de session → alerte.
            on_authorization_refused=self.authorization_lost if owner_source is not None else None,
            # Décision 19 : en mode continu, Voice ne possède plus le modèle
            # fort. Ne pas transmettre la passerelle rend l'interdiction
            # structurelle plutôt que conventionnelle — le bridge n'a
            # simplement plus de quoi appeler Claude.
            claude=None if self.continuous else self.claude,
            conversation_events=self.conversation_events,
        )
        self._bridge = bridge
        if speech is not None:
            # Seul le bridge sait si une sortie joue encore localement.
            speech.output_alive = bridge.output_pending
            await speech.start()
        self._bridge_task = asyncio.create_task(bridge.run(), name="jarvis-realtime-bridge")

    def _duplex_capture(self) -> object | None:
        """Le traitement duplex du micro, créé au premier réveil puis réutilisé."""

        if self.capture_factory is None:
            return None
        if self._capture is None:
            try:
                self._capture = self.capture_factory()
            except Exception as exc:
                # Sans lui, le micro part brut : dégradé, pas bloquant.
                self._trace(
                    "voice.duplex_unavailable",
                    f"Traitement duplex du micro indisponible: {type(exc).__name__}: {exc}",
                    level="warning",
                    data={"code": "duplex_capture_unavailable"},
                )
                self.capture_factory = None
                self._report_capture(None, phase="activation")
                return None
        reset = getattr(self._capture, "reset", None)
        if reset is not None:
            reset()
        self._report_capture(self._capture, phase="activation")
        return self._capture

    def _report_capture(self, capture: object | None, *, phase: str) -> None:
        """Déposer l'état effectif de la capture duplex pour le Control Center (tâche 08).

        Ce que Voice applique vraiment : annulation d'écho active, jamais
        construite (LiveKit absent ou en échec) ou tombée en cours de session
        (`canceller_failed`, la capture continue alors avec la garde seule) ;
        disponibilité du vérificateur et fenêtres perdues par sa file. Lu
        par attributs, sans rien exiger de la capture ; jamais bloquant.
        """

        requested = self.echo_cancellation
        if capture is None:
            active, code = False, "duplex_capture_unavailable"
        elif getattr(capture, "canceller", None) is None:
            active, code = False, ("aec_disabled" if requested is False else "aec_unavailable")
        elif getattr(capture, "canceller_failed", False) is True:
            active, code = False, "aec_failed"
            if not self._aec_failure_traced:
                self._aec_failure_traced = True
                self._trace(
                    "voice.duplex",
                    "Annulation d'écho tombée en cours de session : garde d'écho seule jusqu'au redémarrage de Voice",
                    level="warning",
                    data={"echo_cancellation": False, "requested": True, "code": "duplex_aec_failed"},
                )
        else:
            active, code = True, "aec_active"
        writer = getattr(self.signals, "capture", None)
        if writer is None:
            return
        try:
            observer = getattr(capture, "observer", None)
            verifier: dict[str, object] | None = None
            if observer is not None and hasattr(observer, "availability"):
                availability = observer.availability
                dropped = getattr(observer, "dropped_ms", 0)
                verifier = {
                    "availability": str(getattr(availability, "value", availability)),
                    "dropped_ms": dropped if isinstance(dropped, int) and not isinstance(dropped, bool) else 0,
                }
            writer(
                {
                    "echo_cancellation": {"requested": requested, "active": active, "code": code},
                    "verifier": verifier,
                    # Réglage que ce vérificateur sert, pour que le Control
                    # Center reconnaisse un constat périmé (redémarrage attendu).
                    "speaker_verification": (
                        None if self.authorization_error is not None else self.authorization.verification.value
                    ),
                    # `voice_arch` reste le champ opérationnel historique et
                    # vaut donc `legacy` pour une architecture explicite. Ces
                    # deux identifiants permettent au lecteur d'attribuer le
                    # constat à la composition exacte sans réinterpréter ce
                    # champ de compatibilité.
                    "configuration_id": self.configuration_id,
                    "architecture": (
                        self.conversation_architecture.value
                        if self.conversation_architecture is not None
                        else self.voice_arch.value
                    ),
                    "arch": self.voice_arch.value,
                    "phase": phase,
                }
            )
        except Exception as exc:
            # Le Control Center verra un état plus ancien ; Voice continue.
            self._trace(
                "voice.capture_report_failed",
                f"État de la capture non publié : {type(exc).__name__}",
                level="warning",
                data={"code": "capture_report_failed"},
            )

    def _barge_in_policy(self, capture: object | None):  # noqa: ANN202 - (BargeInAuthority, OwnerStateSource | None)
        """Autorité du barge-in pour la session qui s'ouvre (Solo Owner, tâche 05).

        Salle ouverte (défaut, et retour arrière) : l'autorité acoustique
        d'avant, sans rien tracer de plus. Solo Owner : la confirmation du
        propriétaire, par le vérificateur branché sur la capture duplex.

        Appelé une fois l'activation acceptée (`_authorization_refusal`) : un
        Solo Owner inapplicable ne vient jamais jusqu'ici, il est refusé
        avant, sans repli sur la salle ouverte (tâche 07). Un vérificateur qui
        lâche entre-temps (chargement du modèle pendant la connexion au
        fournisseur) est l'affaire du bridge : il referme l'entrée dès son
        abonnement et désactive la session en le disant. Sans source d'état du
        tout, lever plutôt que dégrader.
        """

        from jarvis.runtime.realtime_audio import BARGE_IN_AUTHORITY_KIND, BargeInAuthority

        authorization = self.authorization
        if not authorization.owner_enforced:
            return BargeInAuthority.ACOUSTIC, None
        source = self._owner_state_source(capture)
        if source is None:
            raise ConfigurationError(
                "Solo Owner sans vérificateur de locuteur branché : l'activation aurait dû être refusée."
            )
        self._trace(
            BARGE_IN_AUTHORITY_KIND,
            "Solo Owner : seule la voix du propriétaire coupe JARVIS et devient un tour",
            data={
                "conversation_id": self.runtime.conversation_id,
                "conversation_mode": authorization.mode.value,
                "speaker_verification": authorization.verification.value,
                "arch": self.voice_arch.value,
                "configured": BargeInAuthority.OWNER.value,
                "availability": self._availability_of(source).value,
                "authority": BargeInAuthority.OWNER.value,
                "status": AuthorizationStatus.READY.value,
            },
        )
        return BargeInAuthority.OWNER, source

    @staticmethod
    def _availability_of(source: object | None) -> VerifierAvailability:
        if source is None:
            return VerifierAvailability.NOT_INSTALLED
        try:
            return VerifierAvailability(getattr(source, "availability"))
        except Exception:
            return VerifierAvailability.FAILED

    @staticmethod
    def _owner_state_source(capture: object | None):  # noqa: ANN205 - OwnerStateSource | None
        """L'état du propriétaire publié par le vérificateur de la capture, s'il y en a un."""

        source = getattr(capture, "observer", None)
        if not all(hasattr(source, name) for name in ("add_owner_listener", "owner_state", "availability")):
            return None
        return source

    def _authorization_refusal(self, capture: object | None) -> tuple[str, str, dict[str, object]] | None:
        """Pourquoi la session qui s'ouvre ne peut pas appliquer Solo Owner, ou None (tâche 07).

        Même verdict que le Control Center (`assess_authorization`, même
        ordre des raisons), plus ce que seul Voice voit : le vérificateur
        réellement branché et sa disponibilité, et une capture capable de
        retenir la voix du propriétaire. Rend (code, message, détails).
        """

        error = self.authorization_error
        if error is not None:
            return (
                error.code,
                f"Réglage de conversation invalide : {error} Voice n'écoute pas tant qu'il n'est pas "
                "corrigé dans runtime/control-center-settings.json (ou conversation_mode remis sur "
                "open_room) ; relancez ensuite Voice.",
                {},
            )
        authorization = self.authorization
        if not authorization.owner_enforced:
            return None
        availability = self._availability_of(self._owner_state_source(capture))
        details: dict[str, object] = {"availability": availability.value}
        assessment = assess_authorization(authorization, availability, continuous=self.continuous)
        if assessment.status is AuthorizationStatus.REFUSED:
            return assessment.code, assessment.message, details
        if not isinstance(getattr(capture, "owner_buffer_ms", None), int) or capture.owner_buffer_ms <= 0:  # type: ignore[union-attr]
            return (
                "solo_owner_capture_unsupported",
                "Mode Solo Owner refusé : la capture duplex n'a pas de tampon de rejeu du propriétaire, elle "
                "ne pourrait pas écarter les autres voix sans perdre le début de vos phrases. Voice n'écoute "
                "pas dans ce mode. Retour arrière : conversation_mode sur open_room, puis relancez Voice.",
                details,
            )
        return None

    def _refuse_activation(self, code: str, message: str, details: dict[str, object], *, phase: str) -> None:
        """Solo Owner inapplicable : ne pas écouter, et dire pourquoi (trace, alerte, Control Center)."""

        from jarvis.runtime.realtime_audio import AUTHORIZATION_REFUSED_KIND

        error = self.authorization_error
        self._trace(
            AUTHORIZATION_REFUSED_KIND,
            message,
            level="warning",
            data={
                "conversation_id": self.runtime.conversation_id,
                "conversation_mode": None if error is not None else self.authorization.mode.value,
                "speaker_verification": None if error is not None else self.authorization.verification.value,
                "arch": self.voice_arch.value,
                "phase": phase,
                "code": code,
                **details,
            },
        )
        if self.signals is not None:
            self.signals.alert(message)
        self._report_authorization("refused", code=code, message=message, phase=phase)

    def _announce_static_refusal(self) -> None:
        """Au démarrage : dire tout de suite ce qui refusera chaque réveil, sans attendre le premier.

        Seules les raisons connues sans ouvrir la capture : réglage illisible,
        Solo Owner sous `legacy`. Le vérificateur, lui, se juge au réveil.
        """

        if self.authorization_error is None and not (self.authorization.owner_enforced and not self.continuous):
            return
        refusal = self._authorization_refusal(None)
        if refusal is not None:
            self._refuse_activation(*refusal, phase="startup")

    async def authorization_lost(self, code: str, message: str) -> None:
        """Le bridge a refermé Solo Owner en cours de session (vérificateur perdu, tâche 07).

        La trace est déjà écrite par le bridge ; ici, ce que l'utilisateur et
        le Control Center voient. Le bridge désactive ensuite la session.
        """

        if self.signals is not None:
            self.signals.alert(message)
        self._report_authorization("refused", code=code, message=message, phase="session")

    def _report_authorization(self, status: str, *, code: str = "", message: str = "", phase: str) -> None:
        """Déposer l'état réel de l'autorisation pour le Control Center (`voice.authorization.runtime`)."""

        writer = getattr(self.signals, "authorization", None)
        if writer is None:
            return
        error = self.authorization_error
        try:
            writer(
                {
                    "status": status,
                    "code": code or None,
                    "problem": message or None,
                    "conversation_mode": None if error is not None else self.authorization.mode.value,
                    "arch": self.voice_arch.value,
                    "phase": phase,
                }
            )
        except Exception as exc:
            # Le Control Center verra un état plus ancien ; Voice continue.
            self._trace(
                "voice.authorization_report_failed",
                f"État de l'autorisation non publié : {type(exc).__name__}",
                level="warning",
                data={"code": "authorization_report_failed"},
            )

    async def submit_active_turn(self, *, source: str) -> bool:
        bridge = self._bridge
        if self.runtime.state is not VoiceLifecycleState.ACTIVE or bridge is None:
            return False
        self._turn_submitted = True
        self._trace("voice.manual_submit", "Manual key submitted the active turn", data={"source": source})
        try:
            submitted = await bridge.submit_input()
            if not submitted:
                if self.signals is not None:
                    self.signals.alert(
                        "Enregistrement trop court. Relancez l'écoute, attendez l'état LISTENING, "
                        "puis parlez avant d'envoyer."
                    )
                await self.mute()
            return submitted
        except Exception as exc:
            self.runtime.state = VoiceLifecycleState.ERROR
            if self.signals is not None:
                self.signals.alert(f"Impossible d'envoyer la commande: {exc}")
            self._trace(
                "voice.input_submit_failed",
                str(exc),
                level="error",
                data={"source": source, "code": "voice_input_submit_failed"},
            )
            await self.mute()
            raise

    async def mute(self, reason=None) -> None:
        from jarvis.domain.voice_frontend import VoiceStopReason
        reason = reason or VoiceStopReason.USER
        if self._mute_task is None or self._mute_task.done():
            initiator = asyncio.current_task()
            if self._bridge_task is not None and self._bridge_task is not initiator:
                self._bridge_task.cancel()  # Stop admission before yielding to the owner task.
            self._mute_task = asyncio.create_task(self._mute_owned(initiator, reason), name="jarvis-voice-mute-owner")
            self._mute_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        await asyncio.shield(self._mute_task)

    async def _mute_owned(self, initiator: asyncio.Task | None, reason) -> None:
        # Arrêté en premier : la parole en file doit périmer avant que la
        # session ne se ferme, et non partir vers un websocket mourant. Ce que
        # l'utilisateur a coupé ne se rattrape pas par une reprise surprise
        # (Décision 33) ; le résultat reste dans Core.
        speech, self._speech = self._speech, None
        if speech is not None:
            await speech.stop()
        self._forget_brain_display()
        bridge, self._bridge = self._bridge, None
        if bridge is not None:
            self._pending_audio = bridge.audio
        bridge_task, self._bridge_task = self._bridge_task, None
        inside_bridge = bridge_task is not None and bridge_task is initiator
        if bridge_task is not None and not inside_bridge:
            if not bridge_task.cancelling():
                bridge_task.cancel()
            await asyncio.gather(bridge_task, return_exceptions=True)
        audio_closed = await self._reconcile_audio_close()
        if not inside_bridge and audio_closed:
            # Micro fermé (le bridge a refermé l'audio) : la capture duplex
            # oublie la session — état du propriétaire compris. Appelé depuis
            # le bridge lui-même, le micro vit encore : l'activation suivante
            # s'en chargera.
            self._end_capture_session()
        session, self._session = self._session, None
        live_record = None
        if session is not None:
            owner = getattr(session, "_lifecycle_owner", None)
            live_record = getattr(owner, "record", None)
            self._metric_live_record = live_record
            try:
                if not await self._close_provider_session(session, reason=reason):
                    return
            except Exception:
                if getattr(session, "canonical_history", False):
                    self._pending_canonical_close = session
                    self.runtime.state = VoiceLifecycleState.ERROR
                raise
            live_record = getattr(owner, "record", live_record)
            self._metric_live_record = live_record
        elif self._pending_canonical_close is not None:
            if not await self._close_provider_session(self._pending_canonical_close, reason=reason):
                return
        if not audio_closed:
            # The provider may already be STOPPED; device ownership is separate.
            self.runtime.state = VoiceLifecycleState.ERROR
            self._visual("thinking")  # Cleanup is pending; ERROR belongs to lifecycle + alert.
            if self.signals is not None:
                self.signals.alert("Audio cleanup is still pending. Voice cannot reopen yet.")
            return
        if not self._stop.is_set():
            await self.wakeword.resume()
        self._turn_submitted = False
        # La session s'en va : plus personne ne réfléchit pour cet écran, et
        # la veille qui suit ne doit pas être repeinte en violet.
        self._brain_working = False
        self.runtime.state = VoiceLifecycleState.BACKGROUND
        if self._metrics is not None:
            self._finish_metrics("stopped", live_record=live_record)
        self._visual("idle")
        self._trace("voice.background", "Voice returned to background")

    async def _close_provider_session(self, session, *, reason=None) -> bool:
        stop = getattr(session, "stop", None)
        result = await stop(reason) if reason is not None and callable(stop) else await session.close()
        if isinstance(result, VoiceOperationResult) and (
            result.status is not VoiceOperationStatus.COMPLETED or result.state is not FrontendState.STOPPED
        ):
            self._pending_canonical_close = session
            self.runtime.state = VoiceLifecycleState.ERROR
            self._trace("voice.provider_close_pending", "Provider closure remains unconfirmed", level="warning",
                        data={"code": "voice_close_unconfirmed", "frontend_state": result.state.value})
            if self.signals is not None:
                self.signals.alert("Voice session closure is unconfirmed. A new session cannot open yet.")
            return False
        if self._pending_canonical_close is session:
            self._pending_canonical_close = None
        return True

    async def _reconcile_audio_close(self) -> bool:
        audio = self._pending_audio
        if audio is None:
            return True
        try:
            closed = await audio.close()
        except Exception as exc:
            self.runtime.state = VoiceLifecycleState.ERROR
            self._trace("voice.device_cleanup_failed", "Audio cleanup failed; device remains owned", level="error",
                        data={"code": "voice_device_cleanup_failed", "exception_type": type(exc).__name__})
            return False
        if closed is False or getattr(audio, "cleanup_pending", False):
            self.runtime.state = VoiceLifecycleState.ERROR
            self._trace("voice.device_cleanup_pending", "Audio cleanup pending; activation unavailable", level="warning",
                        data={"code": "voice_device_cleanup_pending", "cleanup_pending": True})
            return False
        self._pending_audio = None
        return True

    async def _close_failed_evidence(self) -> None:
        try:
            await self.mute()
        except Exception as exc:
            self._trace("voice.evidence_cleanup_pending", "Voice close requires Core reconciliation", level="error",
                        data={"code": "voice_close_reconciliation_pending", "exception_type": type(exc).__name__})

    def _end_capture_session(self) -> None:
        if self._capture is not None:
            # Avant la remise à zéro, qui rend au vérificateur sa disponibilité
            # déclarée : c'est l'état de la session écoulée qu'on publie.
            self._report_capture(self._capture, phase="session_end")
        reset = getattr(self._capture, "reset", None)
        if reset is None:
            return
        try:
            reset()
        except Exception as exc:
            # Best effort : l'activation suivante remet de toute façon la
            # capture à zéro.
            self._trace(
                "voice.duplex_reset_failed",
                f"Remise à zéro de la capture duplex impossible: {type(exc).__name__}",
                level="warning",
                data={"code": "duplex_reset_failed"},
            )

    async def addressed_activity(self) -> None:
        self.activity.reset(AddressingDecision.ADDRESSED)

    async def ambient_activity(self) -> None:
        """Signal entendu mais pas adressé : il ne réarme rien (Décision 10).

        Le tracker ignore volontairement une remise à zéro AMBIENT. Passer
        quand même par ici plutôt que d'ignorer l'évènement rend la règle
        explicite et testable : du bruit, une conversation de fond ou une
        transcription partielle ne prolongent jamais la session.
        """

        self.activity.reset(AddressingDecision.AMBIENT)

    async def brain_activity(self) -> None:
        """Un signal de vie du cerveau réarme le délai d'inactivité (Décision 32).

        Le travail long vit désormais dans Core : sans ce réarmement, un cerveau
        qui travaille trois minutes verrait la voix repasser au fond au bout de
        quatre-vingt-dix secondes, et son résultat n'aurait plus de bouche.

        Le délai repart du **dernier** évènement cerveau, jamais d'une échéance
        fixe : un cerveau bloqué ou muet finit donc par rendre la session, au
        lieu de tenir le micro ouvert indéfiniment. Exception voulue : un délai
        de 0 (« jamais ») laisse la session ouverte jusqu'à la touche de réveil
        ou un mute vocal, cerveau actif ou non.
        """

        from jarvis.domain.voice_architecture import VoiceArchitectureId
        if self.conversation_architecture is not VoiceArchitectureId.DUPLEX:
            self.activity.reset(AddressingDecision.ADDRESSED)

    async def turn_completed(self) -> None:
        """Fin d'un tour en mode continu : on réécoute, on ne se tait pas.

        La réponse achevée est de la parole utile de JARVIS, donc elle réarme
        le délai (Décision 10), mais elle ne touche pas au cycle de vie : la
        session reste ACTIVE jusqu'à un mute, un délai dépassé ou une panne.
        """

        from jarvis.domain.voice_architecture import VoiceArchitectureId
        if self.conversation_architecture is not VoiceArchitectureId.DUPLEX:
            self.activity.reset(AddressingDecision.ADDRESSED)
        self._trace(
            "voice.turn_completed",
            "Tour terminé, la session continue d'écouter",
            data={"conversation_id": self.runtime.conversation_id},
        )
        await self.visual_listening()

    async def visual_listening(self) -> None:
        if self.runtime.state is VoiceLifecycleState.ACTIVE:
            self._visual("listening")

    async def visual_idle(self) -> None:
        """Veille affichée alors que la session reste ACTIVE (mode continu).

        Le micro n'est pas fermé et le cycle de vie ne bouge pas : seul
        l'écran redescend. Une phrase qui n'était pas pour JARVIS ne doit ni
        l'allumer ni lui faire prendre la parole ; le réveil (touche ou
        « Jarvis… ») continue de passer, et rallume l'écoute.
        """

        if self.runtime.state is VoiceLifecycleState.ACTIVE:
            self._visual("idle")

    async def visual_thinking(self) -> None:
        if self.runtime.state is VoiceLifecycleState.ACTIVE:
            self._visual("thinking")

    async def visual_speaking(self) -> None:
        if self.runtime.state is VoiceLifecycleState.ACTIVE:
            # This callback follows an accepted local device write. It is real
            # conversational activity; backend progress/usage callbacks are not.
            self.activity.reset(AddressingDecision.ADDRESSED)
            self._visual("speaking")

    def live_runtime_report(self) -> dict[str, object] | None:
        """Return scalar Duplex supervision data; Core still owns lifecycle truth."""
        from jarvis.domain.voice_architecture import VoiceArchitectureId
        if self.conversation_architecture is not VoiceArchitectureId.DUPLEX:
            return None
        session = self._session or self._pending_canonical_close
        owner = getattr(session, "_lifecycle_owner", None)
        record = getattr(owner, "record", None)
        session_id = getattr(record, "session_id", None)
        remaining = self.activity.remaining_seconds()
        waiting = False
        if remaining == 0 and self.runtime.state is VoiceLifecycleState.ACTIVE:
            waiting = not self._live_idle_ready()
        return {
            "session_id": session_id,
            "model_id": self.conversation_model,
            "configuration_id": self.configuration_id,
            "architecture": self.conversation_architecture.value if self.conversation_architecture else self.voice_arch.value,
            "runtime_state": self.runtime.state.value,
            "idle_enabled": self.activity.enabled,
            "idle_timeout_s": self.activity.timeout_s,
            "idle_remaining_s": remaining,
            "idle_waiting_for_safe_point": waiting,
        }

    def voice_runtime_report(self) -> dict[str, object]:
        session = self._session or self._pending_canonical_close
        return {
            "configuration_id": self.configuration_id,
            "architecture": self.conversation_architecture.value if self.conversation_architecture else self.voice_arch.value,
            "model_id": self.conversation_model,
            "conversation_id": self.runtime.conversation_id,
            "session_id": getattr(session, "session_id", None),
            "runtime_state": self.runtime.state.value,
        }

    async def check_timeout(self) -> bool:
        # Délai à 0 : `expired()` ne devient jamais vrai, donc ni mute ni
        # `voice.timeout_deferred` à chaque tic de la boucle de supervision.
        if self.runtime.state is not VoiceLifecycleState.ACTIVE or not self.activity.expired():
            return False
        # Le délai mesure l'attente de l'utilisateur, pas la durée d'un outil.
        # Couper ici tuait une tâche Claude en plein travail : la session
        # revenait au fond sans un mot pendant que l'agent continuait, et son
        # résultat n'avait plus où revenir.
        #
        # Ce report garde tout son sens en legacy, où le travail long vit dans
        # la tâche du bridge. En mode continu il ne couvre plus que les outils
        # courts de Core : le travail du cerveau appartient à Core, qui survit
        # au retour au fond (Décision 11), et son résultat revient par
        # `/v1/events`. C'est l'ordonnanceur de parole qui réarme le délai à
        # chaque évènement `brain.*` (Décision 32) : le report ci-dessous n'a
        # donc pas à connaître le cerveau, et un cerveau silencieux finit par
        # laisser le délai expirer normalement.
        from jarvis.domain.voice_architecture import VoiceArchitectureId
        duplex = self.conversation_architecture is VoiceArchitectureId.DUPLEX
        if duplex and not self._live_idle_ready():
            return False
        if not duplex and getattr(self._bridge, "tool_in_flight", False):
            self._trace(
                "voice.timeout_deferred",
                "Délai d'inactivité atteint mais un outil travaille encore : session maintenue",
                level="warning",
                data={"conversation_id": self.runtime.conversation_id, "code": "timeout_deferred_tool_running"},
            )
            self.activity.reset()
            return False
        self._trace("voice.timeout", "Useful activity timeout reached")
        if duplex:
            owner = getattr(self._session, "_lifecycle_owner", None)
            if owner is not None:
                try:
                    await owner.idle_candidate()
                except Exception:
                    return False
        from jarvis.domain.voice_frontend import VoiceStopReason
        await self.mute(VoiceStopReason.IDLE)
        return True

    def _live_idle_ready(self) -> bool:
        from jarvis.domain.live_idle import LiveIdleEvidence
        evidence_reader = getattr(self._bridge, "live_idle_evidence", None)
        if not callable(evidence_reader):
            return False
        try:
            evidence = evidence_reader()
        except Exception:
            return False
        if not isinstance(evidence, LiveIdleEvidence):
            return False
        if not evidence.locally_idle:
            return False
        continuation = getattr(self._speech, "immediate_continuation_pending", False)
        return type(continuation) is bool and not continuation

    async def close(self) -> None:
        self._stop.set()
        from jarvis.domain.voice_frontend import VoiceStopReason
        await self.mute(VoiceStopReason.SHUTDOWN)
        if self._pending_canonical_close is not None:
            self._finish_metrics("uncertain")
            self._trace("voice.stop_pending", "Voice provider closure is still unconfirmed", level="warning",
                        data={"code": "voice_close_unconfirmed"})
            return
        if self._pending_audio is not None:
            self._finish_metrics("uncertain")
            # Retain capture/runtime references while native ownership survives.
            self._trace("voice.stop_pending", "Voice provider closed; audio cleanup still pending", level="warning",
                        data={"code": "voice_device_cleanup_pending", "cleanup_pending": True})
            return
        # Après `mute()` : le micro est fermé, plus aucune trame n'arrive. La
        # capture duplex libère son observateur (fil du vérificateur de
        # locuteur), dont l'arrêt peut attendre une fenêtre en cours de calcul.
        capture, self._capture = self._capture, None
        close_capture = getattr(capture, "close", None)
        if close_capture is not None:
            await asyncio.to_thread(close_capture)
        await self.wakeword.close()
        await self.core.close()
        if self.claude is not None:
            await self.claude.close()
        if self.signals is not None:
            self.signals.offline()
        self._trace("voice.stop", "Voice runtime stopped")

    async def mode_switch(self) -> None:
        """Stop the current frontend without cancelling Core-owned work."""
        from jarvis.domain.voice_frontend import VoiceStopReason
        await self.mute(VoiceStopReason.SWITCH)

    def switch_close_pending(self) -> bool:
        return self._pending_canonical_close is not None or self._pending_audio is not None

    def accept_reaped_live_close(self) -> bool:
        """Release a local Live facade only after Core proves no unresolved lease."""
        pending = self._pending_canonical_close
        if pending is None or getattr(pending, "_lifecycle_owner", None) is None:
            return False
        self._pending_canonical_close = None
        self._finish_metrics("stopped")
        return True

    def _finish_metrics(self, status: str, *, live_record=None) -> None:
        metrics = self._metrics
        if metrics is None:
            return
        record = live_record if live_record is not None else self._metric_live_record
        try:
            metrics.finish(status=status, live_record=record)
        except Exception as exc:
            self._trace("voice.metrics.report_failed", "Voice benchmark report failed", level="error",
                        data={"code": "voice_metrics_report_failed",
                              "exception_type": type(exc).__name__})
        else:
            self._metrics = None
            self._metric_live_record = None

    def request_switch_exit(self) -> None:
        self._stop.set()
