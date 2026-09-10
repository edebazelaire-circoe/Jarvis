from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from collections.abc import Callable

from jarvis.core.latency import (
    BRAIN_TURN_ACCEPTED as LATENCY_BRAIN_TURN_ACCEPTED,
    LOCAL_OUTPUT_STOPPED as LATENCY_LOCAL_OUTPUT_STOPPED,
    SURFACE_FIRST_AUDIO as LATENCY_SURFACE_FIRST_AUDIO,
    LatencyTracker,
)
from jarvis.domain.v2 import AddressingDecision, PlaybackCursor, ProtocolEnvelope, SpeechProvenance, new_id
from jarvis.ports.v2 import RealtimeSession, supports_output_control
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.runtime.journal import RuntimeJournal

# Télémétrie de latence (docs/04-testing-and-quality.md, « Latency telemetry »).
# Le journal ne porte que des identifiants, des types et des durées : la clé de
# jointure est nommée dans la charge utile, jamais le texte qui l'a produite.
LATENCY_SURFACE_FIRST_AUDIO_KIND = "voice.latency.surface_first_audio"
LATENCY_BRAIN_TURN_ACCEPTED_KIND = "voice.latency.brain_turn_accepted"


# Mode legacy : cet outil ne va pas à Core, il est intercepté et transmis à
# l'agent Claude, et le bridge attend son résultat.
#
# Mode continu : plus rien n'est attendu ici. Le travail long appartient à Core
# (Décision 01), qui l'a reçu par `submit_brain_turn()` dès le transcript
# complet ; l'outil rend immédiatement un accusé (voir `_brain_owns_the_request`).
CLAUDE_TOOL = "claude_task"

# Erreurs fournisseur qui ne disent rien d'une panne. `response.cancel` part au
# barge-in, pendant que le haut-parleur joue encore l'audio déjà reçu : si le
# fournisseur a fini de générer entre-temps, il refuse l'annulation. Le son est
# déjà coupé localement, le tour est simplement dégradé (voir
# `_cancel_provider_output`) ; en faire une exception fermerait la session.
BENIGN_PROVIDER_ERRORS = frozenset({"response_cancel_not_active"})


def _optional_text(value: object) -> str | None:
    """Normaliser un identifiant de charge utile : vide et absent se valent."""

    return str(value) if value else None


class ConservativeAddressingClassifier:
    FOLLOWUPS = ("oui", "non", "yes", "no", "ok", "d'accord", "et ", "mais ", "alors ", "continue", "pourquoi", "comment", "quand", "où", "qui", "quoi")

    def classify(self, text: str, *, active: bool) -> AddressingDecision:
        normalized = " ".join(text.casefold().strip().split())
        if not normalized:
            return AddressingDecision.AMBIENT
        if normalized.startswith("jarvis"):
            return AddressingDecision.ADDRESSED
        if not active:
            return AddressingDecision.AMBIENT
        if normalized.endswith("?") or normalized.startswith(self.FOLLOWUPS) or len(normalized.split()) <= 8:
            return AddressingDecision.ADDRESSED
        return AddressingDecision.UNCERTAIN


class SoundDeviceRealtimeAudio:
    """24 kHz mono PCM bridge. Raw audio is memory-only and never persisted.

    Toute la difficulté est la fermeture. `asyncio.to_thread` n'interrompt pas
    le thread qu'il a lancé : annuler la tâche du bridge (F9 pendant que JARVIS
    parle) rend la main immédiatement alors que PortAudio écrit toujours dans le
    flux. Fermer celui-ci à cet instant libère la mémoire sous les pieds de
    PortAudio — c'est une violation d'accès (0xC0000005) qui tue le processus
    sans qu'aucun `except` ne puisse s'exécuter. Le verrou ci-dessous est donc
    la seule chose qui garantit qu'aucun thread n'est dans PortAudio au moment
    où le flux est libéré.

    Comptabilité de lecture (curseur de barge-in, spec §12) : la classe tient le
    compte de ce qui a été joué pour la sortie vocale en cours, exposé par
    `playback_cursor()`. Deux verrous distincts, jamais imbriqués :

    - `_output_lock` protège le flux PortAudio, exactement comme avant. Rien
      n'a été ajouté à l'intérieur de sa section critique.
    - `_cursor_lock` protège les seuls compteurs. Il n'est jamais pris pendant
      qu'un thread est à l'intérieur de PortAudio : la boucle d'évènements peut
      donc lire le curseur pendant qu'un bloc de 100 ms s'écrit, sans attendre,
      et l'ordre d'acquisition ne peut pas produire d'interblocage.

    Deux arrêts, pas un : `close()` condamne les deux sens et rend l'objet
    inutilisable, `stop_output()` ne coupe que la parole et laisse le micro
    ouvert (barge-in en mode continu). Tous deux passent par le même
    `_output_lock` avant d'appeler `abort()`.
    """

    # La lecture est découpée pour que la fermeture n'attende jamais plus d'un
    # bloc : l'interruption reste réactive sans jamais couper une écriture.
    OUTPUT_CHUNK_FRAMES = 2400  # 100 ms à 24 kHz, la fréquence de sortie usuelle
    _BYTES_PER_FRAME = 2  # int16 mono

    def __init__(
        self,
        *,
        input_device: int | str | None = None,
        output_device: int | str | None = None,
        sample_rate: int = 24000,
        input_sample_rate: int | None = None,
        output_sample_rate: int | None = None,
    ) -> None:
        self.input_device = input_device
        self.output_device = output_device
        # Les deux sens n'ont pas forcément la même fréquence : OpenAI Realtime
        # travaille en 24 kHz dans les deux sens, Gemini Live veut 16 kHz en
        # entrée et rend 24 kHz. `sample_rate` reste celui de l'entrée, car
        # c'est lui qui sert à convertir des octets capturés en millisecondes.
        self.sample_rate = int(input_sample_rate or sample_rate)
        self.output_sample_rate = int(output_sample_rate or sample_rate)
        self.captured_bytes = 0
        self.sent_bytes = 0
        self._input = None
        self._output = None
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=64)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._output_lock = threading.Lock()
        self._closing = False
        # Comptabilité de lecture : identité de la sortie en cours et octets
        # remis à PortAudio pour elle. `_output_epoch` change à chaque sortie,
        # ce qui permet d'ignorer une écriture qui se termine après la bascule.
        self._cursor_lock = threading.Lock()
        self._output_epoch = 0
        # Époque de lecture : elle avance à chaque changement de sortie **et** à
        # chaque `stop_output()`. Distincte de `_output_epoch`, qui identifie la
        # sortie à créditer : une interruption doit arrêter l'écriture en vol
        # sans lui retirer les blocs qu'elle a déjà réellement joués.
        self._playback_epoch = 0
        self._output_speech_id: str | None = None
        self._output_id: str | None = None
        self._output_response_id: str | None = None
        self._output_item_id: str | None = None
        self._output_written_bytes = 0
        self._output_latency_ms = 0.0

    async def start(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Realtime audio requires sounddevice") from exc
        self._loop = asyncio.get_running_loop()

        def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            del frames, time_info, status
            loop = self._loop
            if loop is None or self._closing:
                return
            try:
                loop.call_soon_threadsafe(self._enqueue, bytes(indata))
            except RuntimeError:
                # La boucle se ferme : les derniers blocs n'ont plus de
                # destinataire, et lever ici ferait tomber le flux PortAudio.
                pass

        def open_streams():
            input_stream = sd.RawInputStream(samplerate=self.sample_rate, channels=1, dtype="int16", device=self.input_device, blocksize=1200, callback=callback)
            try:
                output_stream = sd.RawOutputStream(samplerate=self.output_sample_rate, channels=1, dtype="int16", device=self.output_device)
                input_stream.start(); output_stream.start()
            except Exception:
                self._shutdown_stream(input_stream, abort=True)
                raise
            return input_stream, output_stream

        try:
            # L'ouverture PortAudio coûte plusieurs centaines de millisecondes :
            # la laisser sur la boucle gèle le clavier et les signaux visuels.
            self._input, self._output = await asyncio.to_thread(open_streams)
            with self._cursor_lock:
                self._output_latency_ms = self._stream_latency_ms()
        except Exception as exc:
            await self.close()
            raise RuntimeError(f"Impossible d'ouvrir les périphériques audio Voice: {type(exc).__name__}") from exc

    def _enqueue(self, raw: bytes) -> None:
        self.captured_bytes += len(raw)
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(raw)

    async def pump_input(self, session: RealtimeSession) -> None:
        while True:
            raw = await self._queue.get()
            if raw is None:
                return
            await session.send_audio(raw)
            self.sent_bytes += len(raw)

    async def stop_input(self) -> None:
        stream, self._input = self._input, None
        if stream is not None:
            # Volontairement synchrone : stop() attend la fin des callbacks en
            # vol, et rester sur la boucle garantit que tout ce qu'ils y ont
            # planifié est déjà en file avant le marqueur ci-dessous. Le passer
            # dans un thread ferait perdre les derniers blocs capturés.
            self._shutdown_stream(stream, abort=False)
        # PortAudio has stopped, but its final thread callbacks may still be
        # scheduled on this loop. Enqueue them before the end-of-input marker.
        await asyncio.sleep(0)
        await self._queue.put(None)

    def set_active_output(
        self,
        *,
        speech_id: str | None = None,
        output_id: str | None = None,
        response_id: str | None = None,
        item_id: str | None = None,
    ) -> None:
        """Déclarer la sortie vocale à laquelle la comptabilité s'applique.

        Prévu pour être appelé aussi souvent que nécessaire : les identifiants
        d'une sortie n'arrivent pas tous ensemble — `item_id` n'existe qu'à
        partir de `response.output_item.added`, après l'ouverture de la sortie.
        Tant que la sortie ne change pas, cet appel ne fait que compléter ce qui
        manque ; le compteur n'est remis à zéro que sur un vrai changement, pour
        qu'aucune milliseconde d'une réponse ne soit attribuée à la suivante.

        Une sortie sans aucun identifiant (Gemini Live n'en émet pas,
        Décision 21) ne déclare rien : le curseur reste indisponible.
        """

        identity = output_id or speech_id
        with self._cursor_lock:
            current = self._output_id or self._output_speech_id
            if identity and identity != current:
                self._output_epoch += 1
                self._playback_epoch += 1
                self._output_written_bytes = 0
                self._output_speech_id = speech_id or None
                self._output_id = output_id or None
                self._output_response_id = response_id or None
                self._output_item_id = item_id or None
                self._output_latency_ms = self._stream_latency_ms()
                return
            self._output_speech_id = self._output_speech_id or speech_id or None
            self._output_id = self._output_id or output_id or None
            self._output_response_id = self._output_response_id or response_id or None
            self._output_item_id = self._output_item_id or item_id or None

    def playback_cursor(self) -> PlaybackCursor | None:
        """Ce que l'utilisateur a réellement entendu de la sortie en cours.

        Rend `None` tant qu'aucune sortie n'a été déclarée : il n'y aurait
        alors rien à tronquer côté fournisseur. Quand la sortie n'a pas été
        demandée par un `SpeechRequest` de Core — un réflexe de surface déclenché
        par le VAD serveur —, l'identifiant local de sortie tient lieu
        d'identité ; il est opaque pour Core, et l'adaptateur résout de toute
        façon les identifiants fournisseur en premier.
        """

        with self._cursor_lock:
            speech_id = self._output_speech_id or self._output_id
            if not speech_id:
                return None
            return PlaybackCursor(
                speech_id=speech_id,
                played_ms=self._played_ms_locked(),
                provider_response_id=self._output_response_id,
                provider_item_id=self._output_item_id,
            )

    @property
    def written_output_ms(self) -> int:
        """Millisecondes remises à PortAudio pour la sortie en cours.

        Ce n'est *pas* ce qui a été entendu : au retour de `write()`, l'audio
        est dans le tampon du périphérique, pas encore dans les haut-parleurs.
        """

        with self._cursor_lock:
            return int(self._written_ms_locked())

    @property
    def played_output_ms(self) -> int:
        """Millisecondes réellement jouées, estimation basse assumée.

        `write()` bloque tant que le tampon du périphérique est plein : l'audio
        écrit ne devance donc jamais l'audio joué de plus d'un tampon, dont
        `sounddevice` annonce la durée (`stream.latency`). On retranche cette
        durée de ce qui a été écrit.

        Le sens de l'erreur est choisi, pas subi :

        - à l'interruption, `abort()` jette le contenu du tampon, qui n'est donc
          jamais entendu : l'estimation est alors *exacte*, et c'est le seul cas
          qui compte pour un barge-in ;
        - à la fin naturelle d'une réponse, le tampon se vide et est entendu :
          l'estimation sous-évalue d'au plus un tampon. Tronquer trop court fait
          croire au modèle qu'il a dit moins que ce qui a été entendu, ce qui
          reste conforme au critère d'acceptation (l'historique ne doit jamais
          prétendre que l'utilisateur a entendu de l'audio coupé) ;
        - un flux qui n'annonce pas de latence (flux de test) vaut zéro : le
          curseur se confond alors avec l'audio écrit et surestime d'au plus un
          tampon. Les périphériques réels annoncent toujours leur latence.
        """

        with self._cursor_lock:
            return self._played_ms_locked()

    def _written_ms_locked(self) -> float:
        return self._output_written_bytes * 1000.0 / (self.output_sample_rate * self._BYTES_PER_FRAME)

    def _played_ms_locked(self) -> int:
        return max(0, int(self._written_ms_locked() - self._output_latency_ms))

    def _stream_latency_ms(self) -> float:
        """Durée du tampon de sortie annoncée par le flux, en millisecondes.

        Simple lecture d'attribut : `sounddevice` mémorise la latence à
        l'ouverture du flux, donc rien n'entre ici dans PortAudio et le verrou
        de flux n'est pas requis. La valeur est mémorisée pour rester lisible
        après `close()`, qui a déjà lâché le flux quand 09c lit le curseur.
        """

        latency = getattr(self._output, "latency", None)
        if isinstance(latency, (tuple, list)):
            latency = latency[-1] if latency else None
        try:
            return max(0.0, float(latency) * 1000.0)
        except (TypeError, ValueError):
            # Un flux muet sur sa latence n'est pas une panne : voir le sens de
            # l'erreur documenté sur `played_output_ms`.
            return 0.0

    def _credit_written(self, epoch: int, size: int) -> None:
        with self._cursor_lock:
            if epoch != self._output_epoch:
                # La sortie a changé pendant l'écriture : ces octets
                # appartiennent à la précédente, surtout pas à la nouvelle.
                return
            self._output_written_bytes += size

    async def play_b64(self, value: str) -> None:
        if not value:
            return
        await asyncio.to_thread(self._write_output, base64.b64decode(value))

    def _write_output(self, pcm: bytes) -> None:
        """Écrire la réponse par blocs, verrou tenu.

        Ce thread survit à l'annulation de la tâche qui l'a lancé : le verrou
        est ce qui empêche `close()` de libérer le flux pendant qu'il écrit.

        La comptabilité est volontairement hors de la section critique : un bloc
        n'est crédité qu'une fois `write()` revenu et le verrou de flux relâché.
        Un bloc abandonné parce que le flux se ferme n'est donc jamais compté.

        L'époque de lecture est relue à chaque bloc, sans verrou : `_cursor_lock`
        ne doit jamais être pris à l'intérieur de `_output_lock` (les deux
        verrous ne s'imbriquent pas), et la lecture d'un entier est de toute
        façon indivisible. Qu'elle ait changé signifie que cette écriture ne
        vaut plus — sortie suivante, ou `stop_output()` — et elle s'arrête au
        bloc suivant sans jamais couper un `write()` en cours.
        """
        step = self.OUTPUT_CHUNK_FRAMES * self._BYTES_PER_FRAME
        with self._cursor_lock:
            epoch, playback_epoch = self._output_epoch, self._playback_epoch
        for offset in range(0, len(pcm), step):
            block = pcm[offset:offset + step]
            with self._output_lock:
                stream = self._output
                if stream is None or self._closing or playback_epoch != self._playback_epoch:
                    return
                stream.write(block)
            self._credit_written(epoch, len(block))

    async def stop_output(self) -> None:
        """Couper la lecture en cours sans fermer le flux d'entrée.

        C'est l'arrêt du barge-in (spec §12) : jusqu'ici seul `close()` savait
        interrompre la parole, mais il ferme aussi le micro — inacceptable en
        mode continu, où le tour de l'utilisateur commence précisément par la
        phrase qui coupe JARVIS.

        Même invariant de sûreté que `close()`, pour la même raison : l'époque
        est changée **avant** de prendre le verrou, si bien qu'une écriture en
        vol rend la main au prochain bloc au lieu de faire attendre l'arrêt, et
        `abort()` n'est appelé que le verrou tenu, donc jamais pendant qu'un
        thread est à l'intérieur de PortAudio (violation d'accès 0xC0000005).

        C'est bien l'époque, et non un drapeau rendu à la fin de l'appel, qui
        invalide l'écriture : le thread d'écriture et celui qui interrompt se
        disputent le même verrou, et un drapeau rendu trop tôt laisserait le
        premier reprendre là où il en était — le son repartirait juste après
        l'interruption.

        `abort()` jette le tampon du périphérique au lieu de le vider : ce qui
        y restait n'est jamais entendu, et c'est ce qui rend `played_output_ms`
        exact au moment où le curseur est lu. Le flux est immédiatement
        relancé, car un flux arrêté refuse les écritures suivantes : l'objet
        reste utilisable pour la sortie d'après, sur le même périphérique.

        Ce que ceci n'arrête pas : les blocs que le fournisseur enverrait encore
        pour la sortie coupée, puisqu'ils créeraient de nouvelles écritures. Le
        bridge les écarte à la source (`_output_was_interrupted`).
        """

        with self._cursor_lock:
            # Seule l'époque de lecture avance : ni les compteurs, ni l'identité
            # de la sortie, ni l'époque de comptabilité ne bougent. Le curseur
            # doit rester lisible juste après l'arrêt — c'est lui qui porte la
            # troncature — et le bloc que PortAudio était en train d'écrire a
            # bel et bien été joué, donc il reste crédité.
            self._playback_epoch += 1
        await asyncio.to_thread(self._abort_output)

    def _abort_output(self) -> None:
        with self._output_lock:
            stream = self._output
            if stream is None or self._closing:
                return
            try:
                stream.abort()
                stream.start()
            except Exception:
                # Même politique que `_shutdown_stream` : couper la sortie est
                # au mieux best effort côté périphérique, et lever ici priverait
                # le barge-in de sa troncature alors que le son s'est arrêté.
                pass

    async def close(self) -> None:
        # Signalé avant de prendre le verrou : une lecture en cours s'arrête au
        # prochain bloc au lieu de faire attendre la fermeture jusqu'au bout.
        self._closing = True
        input_stream, self._input = self._input, None
        output_stream, self._output = self._output, None
        if input_stream is None and output_stream is None:
            return
        await asyncio.to_thread(self._shutdown, input_stream, output_stream)

    def _shutdown(self, input_stream, output_stream) -> None:  # noqa: ANN001
        if input_stream is not None:
            self._shutdown_stream(input_stream, abort=False)
        if output_stream is not None:
            # abort() coupe la lecture en cours au lieu de vider le tampon, ce
            # qu'on veut pour une interruption ; le verrou garantit qu'aucun
            # thread n'est alors à l'intérieur de PortAudio.
            with self._output_lock:
                self._shutdown_stream(output_stream, abort=True)

    @staticmethod
    def _shutdown_stream(stream, abort: bool) -> None:  # noqa: ANN001
        try:
            stream.abort() if abort else stream.stop()
            stream.close()
        except Exception:
            # Audio-device teardown is best effort; session shutdown still proceeds.
            pass


class RealtimeConversationBridge:
    """Relie le flux du fournisseur à Core, à l'agent local et aux projections.

    Propriété du micro : le bridge possède le flux d'entrée pour toute la durée
    de `run()`. Il l'ouvre au début, et il n'existe que deux façons de le fermer.

    - Mode legacy : `_close_input()` — sur envoi manuel, ou quand le VAD serveur
      clôt le tour. Le tour suivant passe par une nouvelle session.
    - Mode continu : jamais en cours de session. Le VAD serveur découpe les
      tours dans un flux ininterrompu, et la fermeture unique a lieu dans le
      `finally` de `run()`, exactement comme aujourd'hui lors d'une annulation.

    C'est délibéré : la séquence d'extinction PortAudio de
    `SoundDeviceRealtimeAudio` est difficile à rendre sûre, et rouvrir le flux à
    chaque tour multiplierait les occasions de la prendre en défaut. Le mode
    continu allonge la durée de vie de la capture sans toucher à sa fermeture.

    Contrepartie assumée : micro ouvert pendant que les haut-parleurs jouent.
    Aucune annulation d'écho n'est implémentée ici (spec §11) ; le mode legacy
    reste le repli half-duplex.

    Propriété du travail long : elle a quitté ce bridge en mode continu.

    - Mode legacy : `claude_task` est intercepté, `_call_claude()` attend
      l'agent, et la durée de vie du travail est celle de cette tâche asyncio.
      Annuler le bridge — un `Jarvis Mute` — annule le travail.
    - Mode continu : le transcript complet part vers Core par
      `submit_brain_turn()`, qui rend la main aussitôt. Le travail appartient à
      `BrainOrchestrator`, qui survit à la fermeture de la session vocale
      (Décisions 01 et 11). Ce bridge ne détient plus rien de durable : il
      transporte de l'audio, soumet des tours, et exécute les outils courts de
      Core. La restitution parlée des événements `brain.*` est la tâche 08.
    """

    # Nettement sous le délai d'activité utile le plus court accepté (5 s),
    # pour qu'une tâche longue ne puisse jamais être prise pour un silence.
    CLAUDE_KEEPALIVE_S = 3.0

    def __init__(
        self,
        *,
        core: LocalCoreClient,
        session: RealtimeSession,
        conversation_id: str,
        audio: SoundDeviceRealtimeAudio,
        on_addressed: Callable[[], object],
        on_mute: Callable[[], object],
        on_ambient: Callable[[], object] | None = None,
        on_listening: Callable[[], object] | None = None,
        on_thinking: Callable[[], object] | None = None,
        on_speaking: Callable[[], object] | None = None,
        on_response_done: Callable[[], object] | None = None,
        on_output_event: Callable[[ProtocolEnvelope], object] | None = None,
        on_interruption: Callable[[PlaybackCursor | None], object] | None = None,
        auto_turn: bool = False,
        continuous: bool = False,
        classifier: ConservativeAddressingClassifier | None = None,
        journal: RuntimeJournal | None = None,
        claude=None,
    ) -> None:
        self.core = core
        self.session = session
        self.conversation_id = conversation_id
        self.audio = audio
        self.on_addressed = on_addressed
        self.on_mute = on_mute
        self.on_ambient = on_ambient
        self.on_listening = on_listening
        self.on_thinking = on_thinking
        self.on_speaking = on_speaking
        self.on_response_done = on_response_done
        # Notifie l'ordonnanceur de parole du cycle de vie des sorties vocales.
        # Le bridge reste le seul lecteur de `session.events()` : ouvrir un
        # second flux ferait que les deux boucles se voleraient les évènements.
        self.on_output_event = on_output_event
        # Prévient l'ordonnanceur que la parole en cours a été coupée, avec ce
        # qui en a réellement été entendu. Il est le seul à savoir quelle
        # `SpeechRequest` la sortie restituait, donc le seul à pouvoir rendre
        # l'historique honnête (critère d'acceptation 2).
        self.on_interruption = on_interruption
        self.auto_turn = auto_turn
        # Mode continu : la session couvre plusieurs tours, donc le flux
        # d'entrée n'est jamais fermé entre eux. Voir `_consume`.
        self.continuous = continuous
        self.classifier = classifier or ConservativeAddressingClassifier()
        self.journal = journal
        # Passerelle vers l'agent Claude local. Absente, l'outil `claude_task`
        # répond une indisponibilité prononçable au lieu d'échouer le tour.
        self.claude = claude
        self._pending_action_id: str | None = None
        self._input_task: asyncio.Task[None] | None = None
        self._input_submitted = False
        self._response_had_audio = False
        # Une réponse qui a appelé un outil n'est pas la fin du tour : le
        # résultat en déclenche une seconde, qui portera la parole finale.
        self._tool_result_pending = False
        # Lu par le runtime : un outil en cours interdit le délai d'inactivité.
        self.tool_in_flight = False
        # Dernière réponse de Claude tant qu'elle n'a pas été prononcée.
        self._undelivered_answer: str | None = None
        # Le fournisseur annonce le même appel d'outil sur deux évènements
        # (arguments terminés, puis élément terminé) : sans ce garde, Claude
        # travaille deux fois et le résultat est renvoyé deux fois.
        self._dispatched_calls: set[str] = set()
        # Vrai tant qu'une sortie vocale est ouverte. Volontairement indépendant
        # des identifiants fournisseur : une pile qui n'en émet pas
        # (Décision 21) doit quand même se taire quand l'utilisateur parle.
        self._playing = False
        # Identité de cette sortie quand elle en a une : c'est elle qu'on met
        # sur liste noire après l'avoir coupée.
        self._live_output_identity: str | None = None
        # Sorties coupées dont le fournisseur peut encore émettre des blocs :
        # l'annulation fait un aller-retour websocket, et les rejouer
        # remettrait du son après que l'utilisateur a repris la parole. Borné
        # par le nombre de barge-ins, purgé à la fin de chaque réponse.
        self._interrupted_outputs: set[str] = set()
        # Parole coupée par l'utilisateur, transmise une seule fois au prochain
        # tour cerveau faisant autorité (spec §12, étape 6).
        self._interrupted_speech_id: str | None = None
        # Chronomètre des deux mesures que ce bridge est seul à voir de bout en
        # bout : « l'utilisateur commence à parler → JARVIS émet du son » et
        # « transcript complet → Core a accepté le tour cerveau ». Les deux
        # bornes de chacune sont prises ici, donc sur la même horloge monotone.
        self._latency = LatencyTracker(journal)
        # Segment de parole utilisateur en cours, minté au démarrage du VAD.
        # C'est la clé de jointure de `voice.latency.surface_first_audio`, et il
        # est rappelé sur le tour cerveau pour relier les deux mesures d'un même
        # tour lorsqu'aucune corrélation n'existe encore.
        self._speech_segment_id: str | None = None
        # Sorties dont le premier bloc audio a déjà été relayé à l'ordonnanceur.
        # Sans ce garde, le relais partirait à chaque bloc — cinquante fois par
        # seconde — alors qu'une seule notification suffit à dater la latence.
        # Purgé à la fin de chaque réponse.
        self._audio_notified_outputs: set[str] = set()

    async def _call(self, callback: Callable[[], object] | None) -> None:
        if callback is None:
            return
        value = callback()
        if hasattr(value, "__await__"):
            await value

    async def _call_with(self, callback: Callable[[object], object] | None, argument: object) -> None:
        """Comme `_call`, pour un rappel qui reçoit une valeur."""

        if callback is None:
            return
        value = callback(argument)
        if hasattr(value, "__await__"):
            await value

    @staticmethod
    def _output_identity(payload: dict[str, object]) -> str | None:
        """Nommer la sortie d'un évènement comme le fait `PlaybackCursor`.

        Même règle que `SoundDeviceRealtimeAudio.playback_cursor()` : la
        demande de parole d'abord, l'identifiant local de sortie ensuite pour un
        réflexe de surface qui n'en a pas. Les deux doivent coïncider, sinon le
        curseur d'un barge-in désignerait une sortie que le bridge ne
        reconnaîtrait pas.
        """

        return _optional_text(payload.get("speech_id")) or _optional_text(payload.get("output_id"))

    def _track_playback_output(self, event: ProtocolEnvelope) -> None:
        """Rattacher la comptabilité de lecture à la sortie de cet évènement.

        Appelé à l'ouverture de la sortie *et* sur chaque bloc audio : c'est le
        seul moyen de récupérer `item_id`, qui n'existe qu'après l'ouverture, et
        de recaler la comptabilité si l'ouverture a été manquée. Un évènement
        sans identifiant de sortie ne déclare rien.
        """

        payload = event.payload
        identity = self._output_identity(payload)
        self._playing = True
        if identity:
            self._live_output_identity = identity
        self.audio.set_active_output(
            speech_id=_optional_text(payload.get("speech_id")),
            output_id=_optional_text(payload.get("output_id")),
            response_id=_optional_text(payload.get("response_id")),
            item_id=_optional_text(payload.get("item_id")),
        )

    def _output_was_interrupted(self, payload: dict[str, object]) -> bool:
        """Vrai si cet évènement appartient à une sortie déjà coupée."""

        identity = self._output_identity(payload)
        return identity is not None and identity in self._interrupted_outputs

    def _release_playback_output(self, event: ProtocolEnvelope) -> None:
        """Constater la fin d'une sortie : plus rien ne joue, plus rien à couper."""

        identity = self._output_identity(event.payload)
        self._playing = False
        if identity is None or identity == self._live_output_identity:
            self._live_output_identity = None
        if identity is not None:
            self._interrupted_outputs.discard(identity)
        output_id = _optional_text((event.payload or {}).get("output_id"))
        if output_id is not None:
            self._audio_notified_outputs.discard(output_id)

    async def _barge_in(self) -> None:
        """Interrompre JARVIS parce que l'utilisateur parle (spec §12, mode continu).

        Ordre imposé, et c'est tout l'intérêt de la méthode : l'arrêt local
        d'abord, le fournisseur ensuite. `stop_output()` ne fait qu'un aller
        vers PortAudio, donc l'utilisateur cesse d'entendre JARVIS sans attendre
        le moindre aller-retour réseau ; l'annulation et la troncature ne
        partent qu'après, une fois le curseur figé.

        Rien n'est annulé côté travail : couper la parole n'est pas annuler la
        tâche (Décisions 15 et 35). Le tour utilisateur qui suit portera
        simplement `interrupted_speech_id`, et c'est le cerveau qui décidera.
        """

        started = time.perf_counter()
        await self.audio.stop_output()
        cursor = self.audio.playback_cursor()
        stop_latency_ms = round((time.perf_counter() - started) * 1000, 1)
        interrupted = self._live_output_identity
        if interrupted is not None:
            self._interrupted_outputs.add(interrupted)
        self._playing = False
        self._live_output_identity = None
        self._interrupted_speech_id = cursor.speech_id if cursor is not None else None
        await self._call_with(self.on_interruption, cursor)
        self._trace(
            "voice.barge_in",
            "L'utilisateur a coupé la parole de JARVIS",
            data={
                "conversation_id": self.conversation_id,
                "speech_id": cursor.speech_id if cursor is not None else None,
                "played_ms": cursor.played_ms if cursor is not None else None,
                "provider_item_id": cursor.provider_item_id if cursor is not None else None,
                "output_id": interrupted,
                "stop_latency_ms": stop_latency_ms,
                # Mesure 4 des six de `04-testing-and-quality.md`. Elle est née
                # avec la tranche 09c et n'a pas besoin d'un second évènement :
                # seul son nom manquait pour qu'elle se trouve comme les cinq
                # autres. `speech_id` est sa clé de jointure.
                "measure": LATENCY_LOCAL_OUTPUT_STOPPED,
                "elapsed_ms": stop_latency_ms,
            },
        )
        await self._cancel_provider_output(cursor)

    async def _cancel_provider_output(self, cursor: PlaybackCursor | None) -> None:
        """Annuler la génération, puis aligner l'historique du fournisseur.

        Aucune des deux étapes n'est vitale pour que le son s'arrête — c'est
        déjà fait. Un échec dégrade donc le tour (le modèle croira avoir dit
        plus que ce qui a été entendu) sans jamais casser la session vocale.

        Sans curseur, il n'y a rien à tronquer : une pile qui n'émet pas
        d'identifiant de sortie (Gemini Live, Décision 21) traverse ce chemin
        sans exception.
        """

        if not supports_output_control(self.session):
            self._trace(
                "voice.barge_in_degraded",
                "La pile vocale active ne sait pas annuler sa sortie : le fournisseur continue de générer",
                level="warning",
                data={"conversation_id": self.conversation_id, "code": "barge_in_without_output_control"},
            )
            return
        try:
            await self.session.cancel_output(cursor)
        except Exception as exc:
            self._trace(
                "voice.barge_in_degraded",
                f"Annulation de la sortie refusée par le fournisseur: {type(exc).__name__}: {exc}",
                level="warning",
                data={"conversation_id": self.conversation_id, "code": "barge_in_cancel_failed"},
            )
        if cursor is None:
            self._trace(
                "voice.barge_in_degraded",
                "Aucun curseur de lecture : l'historique du fournisseur n'est pas tronqué",
                level="warning",
                data={"conversation_id": self.conversation_id, "code": "barge_in_without_cursor"},
            )
            return
        try:
            await self.session.truncate(cursor)
        except Exception as exc:
            # `truncate()` lève quand aucun élément fournisseur ne correspond :
            # c'est une troncature impossible, pas une panne de la voix.
            self._trace(
                "voice.barge_in_degraded",
                f"Troncature de l'historique fournisseur impossible: {type(exc).__name__}: {exc}",
                level="warning",
                data={
                    "conversation_id": self.conversation_id,
                    "speech_id": cursor.speech_id,
                    "played_ms": cursor.played_ms,
                    "code": "barge_in_truncate_failed",
                },
            )

    def _open_speech_segment(self) -> str:
        """Ouvrir un segment de parole utilisateur et démarrer son chronomètre.

        Le segment est l'unique chose qui existe à cet instant : le fournisseur
        n'a encore ni transcrit ni corrélé quoi que ce soit. Son identifiant est
        donc la clé de jointure de la mesure 1, et il est rappelé sur la mesure 2
        pour que les deux se lisent comme un seul tour.
        """

        segment_id = new_id()
        self._speech_segment_id = segment_id
        self._latency.mark(LATENCY_SURFACE_FIRST_AUDIO, segment_id)
        return segment_id

    async def _note_first_audio(self, event: ProtocolEnvelope) -> None:
        """Dater le premier son rendu, et n'en prévenir l'ordonnanceur qu'une fois.

        Deux choses distinctes se jouent sur le premier bloc audio d'une sortie.

        1. Mesure 1 : le temps écoulé depuis que l'utilisateur a commencé à
           parler. Elle est fermée quel que soit l'auteur du son — un réflexe de
           surface comme une parole du cerveau —, parce que ce que la mesure
           décrit est le silence qu'a subi l'utilisateur, pas sa provenance.
           `source` dit laquelle des deux a rendu la main.
        2. Mesure 3 : elle appartient à l'ordonnanceur de parole, seul à savoir
           quand la demande du cerveau lui est parvenue. Le bridge est en
           revanche le seul lecteur du flux fournisseur (voir `on_output_event`)
           donc le seul à voir l'audio : il relaie, une fois par sortie.
        """

        payload = event.payload or {}
        speech_id = _optional_text(payload.get("speech_id"))
        # Le segment n'est pas refermé ici : c'est la marque qui est consommée,
        # donc un second bloc audio ne réémet rien, et l'identifiant reste
        # disponible pour relier le tour cerveau à la mesure 1.
        segment_id = self._speech_segment_id
        if segment_id is not None:
            self._latency.measure(
                LATENCY_SURFACE_FIRST_AUDIO,
                segment_id,
                kind=LATENCY_SURFACE_FIRST_AUDIO_KIND,
                data={
                    "conversation_id": self.conversation_id,
                    "segment_id": segment_id,
                    "speech_id": speech_id,
                    "output_id": _optional_text(payload.get("output_id")),
                    "source": SpeechProvenance.BRAIN.value if speech_id else SpeechProvenance.SURFACE_REFLEX.value,
                },
            )
        output_id = _optional_text(payload.get("output_id"))
        if output_id is not None and output_id not in self._audio_notified_outputs:
            self._audio_notified_outputs.add(output_id)
            await self._notify_output(event)

    async def _notify_output(self, event: ProtocolEnvelope) -> None:
        """Relayer un évènement de sortie vocale à l'ordonnanceur de parole."""

        if self.on_output_event is None:
            return
        value = self.on_output_event(event)
        if hasattr(value, "__await__"):
            await value

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, object] | None = None) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=data)

    def _surface_tools_are_closed(self, name: str, *, call_id: str) -> dict[str, object]:
        """Refuser tout outil Core demandé par la surface en mode continu.

        Décision 34 : en continu, la surface n'a aucun outil. Le catalogue vide
        (`tools_for(continuous_brain=True) == []`) est la première barrière — elle
        empêche le modèle de *demander* une action. Ce refus est la seconde : un
        fournisseur qui invente un nom d'outil, une session ouverte avec un
        catalogue périmé ou un modèle qui rejoue un appel d'un tour précédent ne
        doivent pas pouvoir exécuter un outil Core par la bande. Sans ce garde,
        n'importe quel nom autre que `claude_task` atteignait `core.call_tool`
        sans la moindre vérification du mode.

        L'échec est bruyant par construction : une trace de niveau `error` porte
        le nom refusé et son code stable, et le fournisseur reçoit une erreur
        d'outil exploitable — jamais un silence, jamais un succès simulé.
        """

        self._trace(
            "tool.refused",
            name,
            level="error",
            data={"call_id": call_id, "code": "surface_tool_forbidden_in_continuous"},
        )
        return {
            "ok": False,
            "status": "refused",
            "spoken": "",
            "code": "surface_tool_forbidden_in_continuous",
            "error": (
                f"L'outil « {name} » n'est pas disponible pour la surface vocale : "
                "en mode continu, aucune action ne passe par elle."
            ),
            "instruction": (
                "Tu ne disposes d'aucun outil. N'annonce ni action, ni échec, ni "
                "résultat : la demande appartient au cerveau Jarvis, qui l'a déjà reçue."
            ),
        }

    def _brain_owns_the_request(self) -> dict[str, object]:
        """Rendre la main tout de suite : le cerveau possède déjà la demande.

        En mode continu, le transcript complet est parti vers Core avant même
        que le modèle de surface n'appelle cet outil. Attendre ici rouvrirait
        tout ce que cette migration ferme : un appel d'outil Realtime tenu
        ouvert pendant des minutes, une session vocale qu'on n'ose plus couper,
        et un travail long dont la survie dépend d'un websocket.

        La surface ne doit rien annoncer sur cette base : elle n'a ni résultat
        ni progression, seulement un accusé (Décisions 02 et 14). Le
        durcissement des instructions du fournisseur relève de la tâche 06.
        """

        return {
            "ok": True,
            "status": "deferred",
            "spoken": "",
            "code": "brain_owns_the_request",
            "instruction": (
                "La demande est déjà prise en charge par le cerveau Jarvis. "
                "N'annonce ni résultat, ni progression, ni succès : la réponse "
                "sera prononcée quand elle existera."
            ),
        }

    async def _call_claude(self, arguments: dict[str, object]) -> dict[str, object]:
        """Router la demande vers Claude, qui est l'agent capable d'agir sur le PC.

        Chemin **legacy uniquement** (Décision 20) : il bloque le tour vocal le
        temps de la tâche. Le mode continu ne l'emprunte plus — c'est le sens de
        la tâche 07 — mais il reste vivant tant que les recettes poste de
        travail n'ont pas validé le mode continu.

        Une panne de Claude ne doit pas casser le tour vocal : elle revient sous
        forme de texte que JARVIS peut prononcer.
        """
        request = str(arguments.get("request") or "").strip()
        if self.claude is None:
            return {"ok": False, "spoken": "L'agent Claude n'est pas configuré sur cette installation.", "code": "claude_not_configured"}
        await self._call(self.on_thinking)
        # Une tâche Claude de plusieurs minutes n'est pas de l'inactivité : sans
        # ce battement, le délai d'activité utile coupe la session vocale avant
        # que le résultat n'ait un endroit où revenir.
        keepalive = asyncio.create_task(self._keep_session_active(), name="jarvis-claude-keepalive")
        try:
            result = await self.claude.ask(request)
        finally:
            keepalive.cancel()
            await asyncio.gather(keepalive, return_exceptions=True)
        self._trace(
            "claude.answer" if result.get("ok") else "claude.failed",
            str(result.get("spoken") or "")[:300],
            level="info" if result.get("ok") else "error",
            data={"code": result.get("code"), "duration_ms": result.get("duration_ms"), "request": request},
        )
        if result.get("ok"):
            self._undelivered_answer = str(result.get("spoken") or "") or None
        return result

    async def _keep_session_active(self) -> None:
        """Battre tant que l'outil travaille, quoi qu'il arrive à la connexion.

        Le ping et le battement d'activité utile sont deux choses distinctes :
        le premier garde le websocket ouvert, le second dit au runtime que
        l'utilisateur attend toujours quelque chose. Arrêter la boucle sur un
        ping raté supprimait le second aussi, et la session mourait quatre-vingt
        -dix secondes plus tard alors que Claude travaillait encore — sans un
        mot, sans une trace, sans que le résultat ait où revenir.
        """
        ping_failed = False
        while True:
            await asyncio.sleep(self.CLAUDE_KEEPALIVE_S)
            await self._call(self.on_addressed)
            keepalive = getattr(self.session, "keepalive", None)
            if keepalive is None or ping_failed:
                continue
            try:
                await keepalive()
            except Exception as exc:
                # On cesse de pinger une connexion morte, mais on continue de
                # battre : c'est la seule chose qui garde la session en vie
                # jusqu'à ce que Claude rende son résultat.
                ping_failed = True
                self._trace(
                    "provider.keepalive_failed",
                    f"Le websocket Realtime ne répond plus pendant la tâche: {exc}",
                    level="warning",
                    data={
                        "conversation_id": self.conversation_id,
                        "code": "realtime_keepalive_failed",
                    },
                )

    async def _append_legacy_user_turn(self, text: str) -> None:
        """Persister un tour utilisateur par l'ancien chemin (mode legacy seul).

        Point de passage **unique** de `append_turn(kind="user")` dans ce module.
        En mode continu, le tour passe par `submit_brain_turn()`, qui persiste et
        dépêche en une seule opération : emprunter les deux chemins écrirait le
        tour deux fois (Décisions 06 et 30).

        La garde rend l'exclusivité mécanique plutôt que documentaire. Si un
        futur chemin continu retombait ici, il échouerait bruyamment au lieu de
        doubler l'écriture en silence.
        """

        if self.continuous:
            raise RuntimeError(
                "append_turn(kind='user') est interdit en mode continuous_brain : "
                "un tour routé vers le cerveau passe par submit_brain_turn() "
                "(Décisions 06 et 30)."
            )
        await self.core.append_turn(self.conversation_id, kind="user", content=text)

    def _brain_correlation_id(self, provider_item_id: str | None) -> str:
        """Corrélation stable d'un tour, dérivée de l'élément du fournisseur.

        La déduplication de Core repose sur `correlation_id` (Décision 24) :
        elle ne sert à rien si la surface en fabrique un nouveau à chaque
        tentative. Un même élément Realtime rejoué — après une reconnexion, par
        exemple — redonne donc exactement la même valeur, et Core reconnaît le
        doublon au lieu de refaire le travail.

        Sans identifiant fournisseur, on retombe sur un identifiant neuf : deux
        « oui » successifs sont deux tours distincts, et les confondre serait
        pire que de perdre un rejeu.
        """

        if provider_item_id:
            return f"realtime:{self.conversation_id}:{provider_item_id}"
        return new_id()

    async def _submit_brain_turn(
        self,
        text: str,
        *,
        provider_item_id: str | None,
        addressing: AddressingDecision = AddressingDecision.ADDRESSED,
    ) -> bool:
        """Confier un tour utilisateur complet au cerveau possédé par Core.

        Rend la main immédiatement : Core accuse réception, persiste le tour et
        exécute le modèle fort dans sa propre tâche (spec section 4). Le bridge
        n'attend plus rien, donc un mute ne peut plus emporter le travail
        (Décision 11). La suite du tour — parole finale, progression — revient
        par `/v1/events`, hors de ce bridge (tâche 08).

        Rend `True` si Core a pris le tour, `False` s'il l'a refusé. Un refus
        n'interrompt jamais la session vocale : le tour est perdu, la voix
        continue, et la trace dit pourquoi.

        `interrupted_speech_id` ne vaut que pour ce tour-ci : il est consommé,
        y compris quand Core refuse le tour. Le traîner sur le tour suivant
        ferait croire au cerveau que l'utilisateur a coupé une phrase qu'il a
        en réalité laissée finir.

        `addressing` transporte ce que la surface a cru, sans le décider à la
        place du cerveau (Décision 44) : `ADDRESSED` par défaut, `UNCERTAIN`
        quand la phrase est complète mais que rien ne dit qu'elle visait
        JARVIS. La marque suit le tour jusqu'à Core et jusqu'aux traces ; elle
        ne change rien au chemin d'ingress, qui reste unique.
        """

        correlation_id = self._brain_correlation_id(provider_item_id)
        interrupted_speech_id, self._interrupted_speech_id = self._interrupted_speech_id, None
        base = {
            "conversation_id": self.conversation_id,
            "correlation_id": correlation_id,
            "addressing": addressing.value,
            "provider_item_id": provider_item_id,
            "interrupted_speech_id": interrupted_speech_id,
        }
        try:
            acceptance = await self.core.submit_brain_turn(
                self.conversation_id,
                content=text,
                correlation_id=correlation_id,
                source="realtime",
                addressing=addressing.value,
                provider_item_id=provider_item_id,
                interrupted_speech_id=interrupted_speech_id,
            )
        except CoreProtocolError as exc:
            # 503 : Core s'arrête. Aucune boucle de reprise n'existe côté
            # surface, donc ce tour-là est perdu ; mais la corrélation est
            # déterministe, si bien qu'un rejeu du même élément par le
            # fournisseur serait accepté une seule fois par un Core revenu.
            deferred = exc.status == 503
            # Un tour refusé n'a pas de latence d'acceptation : la marque est
            # abandonnée plutôt que léguée au tour suivant, qu'elle ferait
            # paraître arbitrairement lent.
            self._latency.forget(LATENCY_BRAIN_TURN_ACCEPTED, self.conversation_id)
            self._trace(
                "voice.brain_turn_deferred" if deferred else "voice.brain_turn_rejected",
                f"Core a refusé le tour cerveau: {exc}",
                level="warning" if deferred else "error",
                data={**base, "status": exc.status, "code": exc.code},
            )
            return False
        except Exception as exc:
            # Panne de transport vers Core : tracée, jamais silencieuse.
            self._latency.forget(LATENCY_BRAIN_TURN_ACCEPTED, self.conversation_id)
            self._trace(
                "voice.brain_turn_rejected",
                f"Le tour cerveau n'a pas pu être soumis: {type(exc).__name__}: {exc}",
                level="error",
                data={**base, "code": "brain_turn_transport_error"},
            )
            return False
        payload = acceptance if isinstance(acceptance, dict) else {}
        self._trace(
            "voice.brain_turn_submitted",
            text[:300],
            data={
                **base,
                "turn_id": payload.get("turn_id"),
                "revision": payload.get("revision"),
                # Un doublon n'est pas une erreur : Core a reconnu un rejeu et
                # n'a ni repersisté ni redépêché le tour.
                "duplicate": bool(payload.get("duplicate")),
            },
        )
        # Mesure 2 : elle se joint par `correlation_id`, la clé que Core a
        # acceptée, et rappelle le segment de parole pour se relier à la
        # mesure 1 du même tour.
        self._latency.measure(
            LATENCY_BRAIN_TURN_ACCEPTED,
            self.conversation_id,
            kind=LATENCY_BRAIN_TURN_ACCEPTED_KIND,
            data={
                "conversation_id": self.conversation_id,
                "correlation_id": correlation_id,
                "turn_id": payload.get("turn_id"),
                "segment_id": self._speech_segment_id,
                "duplicate": bool(payload.get("duplicate")),
            },
        )
        return True

    def _input_metrics(self) -> dict[str, object]:
        return {
            "conversation_id": self.conversation_id,
            "input_device": self.audio.input_device,
            "captured_bytes": self.audio.captured_bytes,
            "sent_bytes": self.audio.sent_bytes,
            "sent_duration_ms": round(self.audio.sent_bytes * 1000 / (self.audio.sample_rate * 2), 1),
        }

    async def _close_input(self) -> None:
        """Stop capturing and drain the pump so no block is lost or sent late."""
        await self.audio.stop_input()
        input_task, self._input_task = self._input_task, None
        if input_task is not None:
            await input_task

    async def submit_input(self) -> bool:
        if self._input_submitted:
            return False
        if self._input_task is None:
            self._trace(
                "voice.input_skipped",
                "Microphone input is not ready for submission",
                level="warning",
                data={"conversation_id": self.conversation_id, "code": "audio_input_not_ready"},
            )
            return False
        self._input_submitted = True
        self._trace(
            "voice.input_submit_requested",
            "Manual input submission requested",
            data={"conversation_id": self.conversation_id},
        )
        await self._call(self.on_thinking)
        await self._close_input()
        metrics = self._input_metrics()
        if not await self.session.finish_input():
            self._trace(
                "voice.input_skipped",
                "Recorded input is too short to submit",
                level="warning",
                data={**metrics, "code": "audio_input_too_short"},
            )
            return False
        self._trace(
            "voice.input_submitted",
            "Manual input commit and response request sent",
            data=metrics,
        )
        return True

    async def _consume(self, events) -> None:  # noqa: ANN001
        """Traiter le flux du fournisseur.

        Une connexion perdue est une fin de vie normale, pas une panne : le
        websocket Realtime peut être fermé pendant qu'un outil lent travaille.
        Laisser l'exception remonter tuait tout le processus Voice alors que le
        tour venait de réussir.
        """
        try:
            async for event in events:
                if event.message_type == "realtime.audio":
                    self._response_had_audio = True
                    if self._output_was_interrupted(event.payload):
                        # Le fournisseur n'a pas encore vu l'annulation : ces
                        # blocs appartiennent à la phrase que l'utilisateur
                        # vient de couper. Les jouer remettrait du son après le
                        # barge-in, et les créditer fausserait la troncature.
                        continue
                    self._track_playback_output(event)
                    await self._note_first_audio(event)
                    await self._call(self.on_speaking)
                    await self.audio.play_b64(str(event.payload.get("pcm_b64") or ""))
                elif event.message_type == "realtime.audio_done":
                    if self.on_response_done is None:
                        await self._call(self.on_listening)
                elif event.message_type == "realtime.output_started":
                    # JARVIS commence à parler : de la parole utile, donc du
                    # temps rendu à l'utilisateur pour répondre (Décision 10).
                    self._track_playback_output(event)
                    await self._notify_output(event)
                    self._trace(
                        "voice.output_started",
                        "Sortie vocale ouverte",
                        data={
                            "conversation_id": self.conversation_id,
                            "output_id": event.payload.get("output_id"),
                            "speech_id": event.payload.get("speech_id"),
                        },
                    )
                    await self._call(self.on_addressed)
                elif event.message_type == "realtime.transcript_delta":
                    # Transcription partielle de l'entrée : une observation
                    # révisable, pas un tour adressé (Décisions 07 et 10). Elle
                    # ne réarme pas le délai, et elle n'est pas journalisée :
                    # elle arrive plusieurs fois par seconde.
                    await self._call(self.on_ambient)
                elif event.message_type == "realtime.response_done":
                    response_had_audio, self._response_had_audio = self._response_had_audio, False
                    status = str(event.payload.get("status") or "")
                    self._release_playback_output(event)
                    # Avant tout traitement local : c'est la fin de cette sortie
                    # qui libère l'ordonnanceur, y compris quand la réponse
                    # s'arrête sur un appel d'outil.
                    await self._notify_output(event)
                    if self._tool_result_pending:
                        # Cette réponse-ci s'arrête sur l'appel d'outil ; le tour
                        # se terminera sur celle que le résultat vient de créer.
                        self._tool_result_pending = False
                        continue
                    if self.continuous:
                        # Le tour est clos, pas la session : le prochain commit
                        # du VAD serveur ouvrira le suivant sur le même micro.
                        # Le drapeau de commit ne garde plus rien ici — en
                        # legacy il protégeait le mute d'une réponse qu'on
                        # n'avait pas demandée ; en continu la conséquence est
                        # un retour à l'écoute, et s'y fier laisserait la
                        # projection bloquée sur « speaking » après une réponse
                        # interrompue par la parole de l'utilisateur.
                        self._input_submitted = False
                    elif not self._input_submitted:
                        continue
                    if response_had_audio:
                        await self._call(self.on_response_done)
                        continue
                    # Réponse muette : faux départ du VAD annulé par la parole
                    # qui a suivi, échec fournisseur, quota... Sans ce retour la
                    # session resterait « thinking » jusqu'au délai d'activité
                    # utile — quatre-vingt-dix secondes d'écran figé sans un mot.
                    self._trace(
                        "voice.response_silent",
                        "Le fournisseur a terminé sans audio : tour clos sans réponse vocale",
                        level="warning",
                        data={
                            "conversation_id": self.conversation_id,
                            "status": status or "unknown",
                            "code": "realtime_response_without_audio",
                        },
                    )
                    await self._rescue_undelivered_answer()
                    await self._call(self.on_response_done or self.on_mute)
                elif event.message_type == "realtime.speech_started":
                    # Borne de départ de la mesure 1, posée avant toute
                    # décision : que ce segment coupe la parole de JARVIS ou
                    # ouvre un tour, le délai jusqu'au premier son rendu est le
                    # même chiffre pour l'utilisateur.
                    self._open_speech_segment()
                    if self.continuous and self._playing:
                        # Barge-in : JARVIS parle et l'utilisateur enchaîne. Le
                        # chemin legacy, half-duplex, ne peut pas se trouver
                        # dans cet état — il garde donc exactement sa trace.
                        await self._barge_in()
                    elif self.auto_turn and not self._input_submitted:
                        self._trace(
                            "voice.speech_started",
                            "Speech detected by server VAD",
                            data={"conversation_id": self.conversation_id},
                        )
                elif event.message_type == "realtime.input_committed":
                    if self.auto_turn and self.continuous:
                        # Le micro reste ouvert : c'est le VAD serveur qui
                        # découpe les tours, et fermer le flux ici condamnerait
                        # la session au tour unique. Un commit qui arrive alors
                        # qu'une réponse joue encore est une interruption
                        # légitime, pas un segment perdu : la lecture a déjà été
                        # coupée et l'historique tronqué sur
                        # `realtime.speech_started` (voir `_barge_in`).
                        self._input_submitted = True
                        self._trace(
                            "voice.input_submitted",
                            "Server VAD closed a turn inside the continuous session",
                            data=self._input_metrics(),
                        )
                        await self._call(self.on_thinking)
                    elif self.auto_turn and not self._input_submitted:
                        self._input_submitted = True
                        # The provider already holds the turn; releasing the microphone
                        # here keeps the speakers from feeding the next VAD segment.
                        await self._close_input()
                        self._trace(
                            "voice.input_submitted",
                            "Server VAD closed the turn and requested a response",
                            data=self._input_metrics(),
                        )
                        await self._call(self.on_thinking)
                    elif self.auto_turn:
                        # Le micro était déjà fermé : ce segment est la suite de
                        # phrase que le VAD a coupée, et le fournisseur l'a mise
                        # dans un tour que personne n'écoute. Le tracer est la
                        # seule façon de voir, après coup, qu'on a été coupé.
                        self._trace(
                            "voice.input_dropped",
                            "Segment capté après la clôture du tour : il ne sera pas traité",
                            level="warning",
                            data={
                                "conversation_id": self.conversation_id,
                                "code": "audio_input_after_commit",
                            },
                        )
                elif event.message_type == "realtime.transcript":
                    # Borne de départ de la mesure 2. Prise avant le classement
                    # d'adressage : ce qui est chronométré est le chemin complet
                    # « transcript complet → Core a accepté », décision de
                    # surface comprise.
                    self._latency.mark(LATENCY_BRAIN_TURN_ACCEPTED, self.conversation_id)
                    text = str(event.payload.get("text") or "").strip()
                    decision = self.classifier.classify(text, active=True)
                    self._trace("voice.transcript", text or "<empty>", data={"addressing": decision.value})
                    if self.continuous and decision is AddressingDecision.UNCERTAIN:
                        # Décision 44 : décider qu'une demande n'en est pas une
                        # est une décision d'intention, et l'intention
                        # appartient au cerveau. En continu, un tour complet
                        # dont l'adressage est douteux part donc vers Core au
                        # lieu d'être jeté, avec la marque du doute.
                        #
                        # Le doute n'est pas de l'activité utile : on passe par
                        # `on_ambient` exactement comme avant, ce qui laisse le
                        # minuteur d'inactivité où il est (Décision 10). Router
                        # et réarmer sont deux choses distinctes ; seul le
                        # cerveau, s'il donne signe de vie sur ce tour, réarmera
                        # (Décision 32). Pour la même raison, ni `on_thinking`
                        # ni `on_addressed` ne sont appelés : la surface ne
                        # doit pas afficher qu'elle travaille pour l'utilisateur
                        # sur une phrase qui ne lui était peut-être pas
                        # adressée.
                        #
                        # « Jarvis mute » ne peut pas tomber ici : toute phrase
                        # commençant par « jarvis » est classée ADDRESSED, donc
                        # la commande reste traitée plus bas, avant tout envoi
                        # au cerveau, exactement comme avant.
                        await self._call(self.on_ambient)
                        await self._submit_brain_turn(
                            text,
                            provider_item_id=str(event.payload.get("item_id") or "") or None,
                            addressing=decision,
                        )
                        continue
                    if decision is not AddressingDecision.ADDRESSED:
                        # Entendu, mais pas pour JARVIS : le délai d'activité
                        # utile ne bouge pas (Décision 10). AMBIENT est jeté
                        # dans les deux modes ; UNCERTAIN ne parvient ici qu'en
                        # legacy, où la surface possède les outils et garde son
                        # rôle d'arbitre (Décisions 20 et 44).
                        await self._call(self.on_ambient)
                        continue
                    normalized = " ".join(text.casefold().replace(",", " ").split())
                    if normalized == "jarvis mute":
                        await self._call(self.on_mute)
                        break
                    if self.continuous:
                        # Chemin autoritaire unique : persistance et dépêche du
                        # cerveau en une seule opération côté Core.
                        await self._submit_brain_turn(
                            text,
                            provider_item_id=str(event.payload.get("item_id") or "") or None,
                        )
                    else:
                        await self._append_legacy_user_turn(text)
                    await self._call(self.on_thinking)
                    if self._pending_action_id is not None and normalized in {"oui", "non", "yes", "no"}:
                        result = await self.core.confirm_action(self._pending_action_id, text)
                        if result.get("disposition") != "confirm":
                            self._pending_action_id = None
                        await self.session.send_context("Jarvis Core confirmation result: " + str(result))
                    await self._call(self.on_addressed)
                elif event.message_type == "realtime.assistant_transcript":
                    text = str(event.payload.get("text") or "").strip()
                    speech_id = str(event.payload.get("speech_id") or "")
                    if text and speech_id:
                        # Cette réponse restitue une demande de parole du
                        # cerveau : c'est l'ordonnanceur qui persiste le tour,
                        # avec la provenance `brain.speech` et le texte
                        # autoritaire (spec section 15). Écrire ici aussi
                        # persisterait le même tour deux fois, dont une fois
                        # sous une provenance fausse.
                        self._undelivered_answer = None
                        self._trace("voice.assistant", text, data={"speech_id": speech_id, "provenance": SpeechProvenance.BRAIN.value})
                        await self._call(self.on_addressed)
                    elif text:
                        # JARVIS a parlé : le résultat de l'outil est arrivé
                        # jusqu'à l'utilisateur, plus rien à sauver.
                        self._undelivered_answer = None
                        self._trace("voice.assistant", text)
                        # Un tour assistant reste légitime par ce chemin
                        # (Décision 30). En continu on l'étiquette : ce que la
                        # surface prononce d'elle-même est un réflexe, pas la
                        # parole du cerveau (spec section 15).
                        if self.continuous:
                            await self.core.append_turn(
                                self.conversation_id,
                                kind="assistant",
                                content=text,
                                metadata={"provenance": SpeechProvenance.SURFACE_REFLEX.value},
                            )
                        else:
                            await self.core.append_turn(self.conversation_id, kind="assistant", content=text)
                        await self._call(self.on_addressed)
                elif event.message_type == "realtime.tool_call":
                    call_id = str(event.payload.get("call_id") or "")
                    name = str(event.payload.get("name") or "")
                    arguments = event.payload.get("arguments") if isinstance(event.payload.get("arguments"), dict) else {}
                    if call_id and call_id in self._dispatched_calls:
                        self._trace(
                            "tool.duplicate",
                            name,
                            level="warning",
                            data={"call_id": call_id, "code": "tool_call_already_dispatched"},
                        )
                        continue
                    if call_id:
                        self._dispatched_calls.add(call_id)
                    self._trace("tool.call", name, data={"call_id": call_id, "arguments": arguments})
                    # Le délai d'activité utile mesure l'attente de l'utilisateur,
                    # pas la durée d'un outil : tant que celui-ci travaille, la
                    # session ne doit pas pouvoir être coupée sous ses pieds.
                    # Ce drapeau ne couvre plus que les outils que le bridge
                    # exécute lui-même. En mode continu, le travail long a
                    # quitté ce processus : il n'est plus « en vol » ici, et
                    # rien de ce qui suit ne dure.
                    self.tool_in_flight = True
                    try:
                        if name == CLAUDE_TOOL:
                            result = self._brain_owns_the_request() if self.continuous else await self._call_claude(arguments)
                        elif self.continuous:
                            result = self._surface_tools_are_closed(name, call_id=call_id)
                        else:
                            result = await self.core.call_tool(name, arguments, conversation_id=self.conversation_id)
                    finally:
                        self.tool_in_flight = False
                    self._trace("tool.result", name, data={"call_id": call_id, "result": result})
                    action_id = result.get("action_id")
                    self._pending_action_id = str(action_id) if result.get("disposition") == "confirm" and action_id else None
                    self._tool_result_pending = True
                    await self.session.send_tool_result(call_id, result)
                elif event.message_type == "realtime.error":
                    error = event.payload.get("error") or {}
                    if isinstance(error, dict):
                        code = str(error.get("code") or "unknown_error")
                        message = str(error.get("message") or error)
                    else:
                        code = "unknown_error"
                        message = str(error)
                    if code in BENIGN_PROVIDER_ERRORS:
                        self._trace(
                            "voice.barge_in_degraded",
                            f"Annulation de la sortie refusée par le fournisseur: {message}",
                            level="warning",
                            data={"conversation_id": self.conversation_id, "code": code},
                        )
                        continue
                    self._trace("provider.error", message, level="error", data={"code": code})
                    raise RuntimeError(f"Realtime provider error [{code}]: {message}")
        except ConnectionError as exc:
            self._trace(
                "provider.disconnected",
                f"Connexion Realtime perdue: {exc}",
                level="warning",
                data={"code": "realtime_disconnected", "conversation_id": self.conversation_id},
            )
            await self._rescue_undelivered_answer()

    async def _rescue_undelivered_answer(self) -> None:
        """Sauver la réponse de Claude quand la voix ne peut plus la porter.

        Une tâche de plusieurs minutes qui aboutit puis se perd parce que le
        websocket s'est fermé entre-temps, c'est le pire des cas : l'utilisateur
        a attendu et n'a rien — ni voix, ni texte, ni erreur. Elle est donc
        écrite dans la conversation et dans la liste d'erreurs du Control
        Center, qui est le seul canal encore debout à ce stade.

        Sans objet en mode continu, et retiré de ce mode : la réponse n'a jamais
        transité par ce processus. Elle est produite, persistée et publiée par
        Core, qui survit à la fermeture de la session vocale (Décision 11).
        Écrire ici reviendrait à réintroduire une seconde écriture concurrente
        de celle de Core, exactement ce que la Décision 06 interdit.
        """
        if self.continuous:
            return
        answer, self._undelivered_answer = self._undelivered_answer, None
        if not answer:
            return
        self._trace(
            "claude.answer_undelivered",
            answer[:300],
            level="error",
            data={"conversation_id": self.conversation_id, "code": "claude_answer_undelivered"},
        )
        try:
            await self.core.append_turn(self.conversation_id, kind="assistant", content=answer)
        except Exception:
            # Core est peut-être tombé lui aussi ; la trace ci-dessus suffit.
            pass

    async def run(self) -> None:
        await self.audio.start()
        self._trace(
            "audio.start",
            "Realtime microphone and speaker opened",
            data={"input_device": self.audio.input_device, "output_device": self.audio.output_device},
        )
        self._input_task = asyncio.create_task(self.audio.pump_input(self.session), name="jarvis-realtime-mic")
        try:
            await self._call(self.on_listening)
            await self._consume(self.session.events())
        finally:
            input_task, self._input_task = self._input_task, None
            if input_task is not None:
                input_task.cancel()
                await asyncio.gather(input_task, return_exceptions=True)
            await self.audio.close()
            self._trace("audio.stop", "Realtime microphone and speaker closed")
