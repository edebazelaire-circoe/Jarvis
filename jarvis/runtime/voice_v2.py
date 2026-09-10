from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from jarvis.core.v2_services import SystemClock
from jarvis.domain.errors import ConfigurationError
from jarvis.domain.v2 import AddressingDecision, VoiceLifecycleState
from jarvis.ports.v2 import Clock, RealtimeSession, WakeWordBackend, supports_output_control
from jarvis.protocol.client import LocalCoreClient
from jarvis.runtime.journal import RuntimeJournal
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
      tours, ce qui expose un risque d'écho acoustique réel et non traité ici
      (spec §11) : `LEGACY` reste le repli half-duplex.

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
    ) -> None:
        self.voice_arch = voice_arch
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
        self.runtime = VoiceRuntimeState()
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
        self._session: RealtimeSession | None = None
        self._bridge = None
        self._bridge_task: asyncio.Task[None] | None = None
        # Ordonnanceur de la parole du cerveau. Sa durée de vie est celle du
        # transport vocal ACTIF, pas celle du travail : il naît avec la session
        # et meurt au mute, tandis que le travail continue dans Core.
        self._speech: SpeechScheduler | None = None
        self._turn_submitted = False
        self._stop = asyncio.Event()
        self._visual("idle")

    @property
    def continuous(self) -> bool:
        """Vrai quand une session ACTIVE doit couvrir plusieurs tours."""

        return self.voice_arch is VoiceArchitecture.CONTINUOUS_BRAIN

    def _visual(self, state: str) -> None:
        if self.signals is not None:
            self.signals.state(state)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, object] | None = None) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=data)

    async def run(self) -> None:
        if self.signals is not None:
            self.signals.heartbeat()
        self._trace("voice.start", "Voice runtime started")
        detections = self.wakeword.detections()
        detection_task: asyncio.Task[str] | None = None
        try:
            while not self._stop.is_set():
                if detection_task is None:
                    detection_task = asyncio.create_task(anext(detections), name="jarvis-manual-toggle")

                if self.runtime.state is VoiceLifecycleState.BACKGROUND:
                    try:
                        keyword = await detection_task
                    except StopAsyncIteration:
                        break
                    detection_task = None
                    self._trace("voice.wake", "Wake detected", data={"source": keyword})
                    await self.activate()
                    continue

                bridge_task = self._bridge_task
                if bridge_task is None:
                    await self.mute()
                    continue

                done, _ = await asyncio.wait({detection_task, bridge_task}, return_when=asyncio.FIRST_COMPLETED)
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
                    await self.mute()
                if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                    self._trace("voice.failure", str(outcome), level="error")
                    raise outcome
        finally:
            if detection_task is not None:
                detection_task.cancel()
                await asyncio.gather(detection_task, return_exceptions=True)
            await self.close()

    async def activate(self) -> None:
        if self.runtime.state is not VoiceLifecycleState.BACKGROUND:
            return
        self.runtime.state = VoiceLifecycleState.CONNECTING
        self._visual("thinking")
        self._trace("voice.connecting", "Opening Realtime session")
        if self.runtime.conversation_id is None:
            conversation = await self.core.create_conversation()
            self.runtime.conversation_id = str(conversation["id"])
        context = await self.core.context(self.runtime.conversation_id)
        try:
            self._session = await self.realtime_factory(context)
        except Exception as exc:
            self.runtime.state = VoiceLifecycleState.ERROR
            if self.signals is not None:
                self.signals.alert(str(exc))
            self._trace("voice.provider_error", str(exc), level="error")
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
        self.runtime.state = VoiceLifecycleState.ACTIVE
        if self.signals is not None:
            self.signals.alert(None)
        self._trace(
            "voice.active",
            "Realtime session active",
            data={"conversation_id": self.runtime.conversation_id, "arch": self.voice_arch.value},
        )
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
            )
            if self.continuous
            else None
        )
        self._speech = speech
        bridge = RealtimeConversationBridge(
            core=self.core,
            session=self._session,
            conversation_id=self.runtime.conversation_id,
            audio=SoundDeviceRealtimeAudio(
                input_device=self.audio_input_device,
                output_device=self.audio_output_device,
                input_sample_rate=self.input_sample_rate,
                output_sample_rate=self.output_sample_rate,
            ),
            on_addressed=self.addressed_activity,
            on_ambient=self.ambient_activity,
            on_mute=self.mute,
            on_listening=self.visual_listening,
            on_thinking=self.visual_thinking,
            on_speaking=self.visual_speaking,
            # Décision 08 : en continu, une réponse terminée rouvre l'écoute au
            # lieu de rendre la main au mot d'éveil.
            on_response_done=self.turn_completed if self.continuous else self.mute,
            on_output_event=speech.note_output_event if speech is not None else None,
            # Tâche 09 : le bridge coupe la lecture, l'ordonnanceur sait quelle
            # demande de parole y était rattachée. Sans ce fil, l'historique
            # présenterait comme entendue une phrase tronquée.
            on_interruption=speech.note_interruption if speech is not None else None,
            auto_turn=self.auto_turn,
            continuous=self.continuous,
            journal=self.journal,
            # Décision 19 : en mode continu, Voice ne possède plus le modèle
            # fort. Ne pas transmettre la passerelle rend l'interdiction
            # structurelle plutôt que conventionnelle — le bridge n'a
            # simplement plus de quoi appeler Claude.
            claude=None if self.continuous else self.claude,
        )
        self._bridge = bridge
        if speech is not None:
            await speech.start()
        self._bridge_task = asyncio.create_task(bridge.run(), name="jarvis-realtime-bridge")

    async def submit_active_turn(self, *, source: str) -> bool:
        bridge = self._bridge
        if self.runtime.state is not VoiceLifecycleState.ACTIVE or bridge is None:
            return False
        self._turn_submitted = True
        self._trace("voice.manual_submit", "Manual key submitted the active turn", data={"source": source})
        try:
            submitted = await bridge.submit_input()
            if not submitted:
                await self.mute()
                if self.signals is not None:
                    self.signals.alert(
                        "Enregistrement trop court. Relancez l'écoute, attendez l'état LISTENING, "
                        "puis parlez avant d'envoyer."
                    )
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

    async def mute(self) -> None:
        # Arrêté en premier : la parole en file doit périmer avant que la
        # session ne se ferme, et non partir vers un websocket mourant. Ce que
        # l'utilisateur a coupé ne se rattrape pas par une reprise surprise
        # (Décision 33) ; le résultat reste dans Core.
        speech, self._speech = self._speech, None
        if speech is not None:
            await speech.stop()
        self._bridge = None
        bridge_task, self._bridge_task = self._bridge_task, None
        if bridge_task is not None and bridge_task is not asyncio.current_task():
            bridge_task.cancel()
            await asyncio.gather(bridge_task, return_exceptions=True)
        session, self._session = self._session, None
        if session is not None:
            await session.close()
        if not self._stop.is_set():
            await self.wakeword.resume()
        self._turn_submitted = False
        self.runtime.state = VoiceLifecycleState.BACKGROUND
        self._visual("idle")
        self._trace("voice.background", "Voice returned to background")

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

        self.activity.reset(AddressingDecision.ADDRESSED)

    async def turn_completed(self) -> None:
        """Fin d'un tour en mode continu : on réécoute, on ne se tait pas.

        La réponse achevée est de la parole utile de JARVIS, donc elle réarme
        le délai (Décision 10), mais elle ne touche pas au cycle de vie : la
        session reste ACTIVE jusqu'à un mute, un délai dépassé ou une panne.
        """

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

    async def visual_thinking(self) -> None:
        if self.runtime.state is VoiceLifecycleState.ACTIVE:
            self._visual("thinking")

    async def visual_speaking(self) -> None:
        if self.runtime.state is VoiceLifecycleState.ACTIVE:
            self._visual("speaking")

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
        if getattr(self._bridge, "tool_in_flight", False):
            self._trace(
                "voice.timeout_deferred",
                "Délai d'inactivité atteint mais un outil travaille encore : session maintenue",
                level="warning",
                data={"conversation_id": self.runtime.conversation_id, "code": "timeout_deferred_tool_running"},
            )
            self.activity.reset()
            return False
        self._trace("voice.timeout", "Useful activity timeout reached")
        await self.mute()
        return True

    async def close(self) -> None:
        self._stop.set()
        await self.mute()
        await self.wakeword.close()
        await self.core.close()
        if self.claude is not None:
            await self.claude.close()
        if self.signals is not None:
            self.signals.offline()
        self._trace("voice.stop", "Voice runtime stopped")
