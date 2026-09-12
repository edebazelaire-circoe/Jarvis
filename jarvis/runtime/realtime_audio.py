from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
import unicodedata
from collections import deque
from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING

from jarvis.core.latency import (
    BRAIN_TURN_ACCEPTED as LATENCY_BRAIN_TURN_ACCEPTED,
    LOCAL_OUTPUT_STOPPED as LATENCY_LOCAL_OUTPUT_STOPPED,
    SURFACE_FIRST_AUDIO as LATENCY_SURFACE_FIRST_AUDIO,
    LatencyTracker,
)
from jarvis.domain.speaker import OwnerState, OwnerStateSnapshot, VerifierAvailability
from jarvis.domain.v2 import AddressingDecision, PlaybackCursor, ProtocolEnvelope, SpeechProvenance, new_id
from jarvis.ports.v2 import RealtimeSession, supports_output_control
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.turn_filters import EchoGuard, looks_like_request, mentions_jarvis, noise_reason, words

if TYPE_CHECKING:
    from jarvis.audio.duplex import CaptureProcessor
    from jarvis.ports.speaker import OwnerStateSource

# Signal de la capture duplex : l'utilisateur parle par-dessus JARVIS. Même
# valeur que `jarvis.audio.duplex.NEAR_END`, recopiée pour que ce module
# n'importe pas numpy (un test garde les deux en phase).
NEAR_END_SIGNAL = "near_end"
# Signal de la capture duplex : un préfixe du propriétaire a été rejoué vers le
# fournisseur (`jarvis.audio.duplex.OWNER_REPLAY`, recopié pour la même raison).
OWNER_REPLAY_SIGNAL = "owner_replay"
# Signal de la file d'envoi : un bloc portant un rejeu du propriétaire a tout de
# même été perdu. Ne vient pas de la capture ; produit par `_put_input`.
OWNER_REPLAY_DROPPED_SIGNAL = "owner_replay_dropped"


class BargeInAuthority(StrEnum):
    """Ce qui a le droit de faire taire JARVIS pendant qu'il parle (Solo Owner, tâche 05).

    Politique de *déclenchement* seulement. L'arrêt lui-même ne dépend pas
    d'elle : arrêt local d'abord, curseur figé, sorties reçues mises sur liste
    noire, puis annulation et troncature fournisseur en suivi best effort
    (`RealtimeConversationBridge._barge_in`).

    - `ACOUSTIC` : le comportement historique, salle ouverte. La parole proche
      captée localement baisse la voix de JARVIS, le `speech_started` du
      fournisseur la coupe.
    - `OWNER` : Solo Owner (D04, D05, D09). Seule la confirmation locale du
      propriétaire par le vérificateur de locuteur coupe. La parole proche ne
      touche plus au volume ; `speech_started` ne sert qu'à corréler. Avec une
      capture qui sait rejouer (tâche 06), elle n'ouvre plus non plus le flux
      vers le fournisseur : c'est la confirmation du propriétaire qui l'ouvre,
      début de phrase rejoué — que JARVIS parle ou se taise (tâche 07). Une
      autre voix ne devient ni tour, ni réflexe, ni activité utile.
    """

    ACOUSTIC = "acoustic"
    OWNER = "owner"


# Diagnostics du barge-in Solo Owner : scalaires seulement, jamais d'audio ni
# d'empreinte vocale. Les instants sont ceux de l'horloge de la capture.
BARGE_IN_AUTHORITY_KIND = "voice.barge_in.authority"
BARGE_IN_OWNER_CONFIRMED_KIND = "voice.barge_in.owner_confirmed"
BARGE_IN_PROVIDER_ADVISORY_KIND = "voice.barge_in.provider_advisory"
# Rejeu du début de phrase du propriétaire (tâche 06) : mêmes règles.
OWNER_REPLAY_KIND = "voice.owner.replay"
# Solo Owner, entrée filtrée par l'identité (tâche 07). Entrée écartée : raison,
# scalaires, jamais le texte ni l'audio. Même nom que l'évènement de la capture
# (`jarvis.audio.speaker_shadow.OWNER_INPUT_DROPPED`), `source` les distingue.
INPUT_NON_OWNER_DROPPED_KIND = "voice.input.non_owner_dropped"
# Solo Owner refusé ou suspendu : code stable et message en clair.
AUTHORIZATION_REFUSED_KIND = "voice.authorization_refused"

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

# Erreurs qui perdent une phrase sans condamner la session : une réponse
# demandée pendant qu'une autre génère encore est refusée, la suivante passera.
RECOVERABLE_PROVIDER_ERRORS = frozenset({"conversation_already_has_active_response"})

# Évènements fournisseur rattachés à l'audio qui les précède : ils ne sont
# traités qu'une fois cet audio réellement joué (voir `_consume`).
ORDERED_OUTPUT_EVENTS = frozenset(
    {
        "realtime.output_started",
        "realtime.audio_done",
        "realtime.response_done",
        "realtime.assistant_transcript",
    }
)

# Accusé de réception de surface : réservé aux vraies demandes. « Merci »,
# « d'accord » ou un « oui » de confirmation n'appellent pas de « je m'en
# occupe » — le cerveau y répond directement.
REFLEX_MIN_WORDS = 4


def _optional_text(value: object) -> str | None:
    """Normaliser un identifiant de charge utile : vide et absent se valent."""

    return str(value) if value else None


class ConservativeAddressingClassifier:
    """Ce que la surface croit de l'adressage d'une phrase complète.

    `engaged` dit si l'utilisateur est en conversation avec JARVIS : réveil
    récent, réponse de JARVIS ou demande adressée il y a peu (fenêtre tenue par
    le bridge en mode continu). `None` : pas de fenêtre (mode legacy, un tour
    par appui, toujours engagé).

    - Nom prononcé : adressé, toujours.
    - Pas engagé : incertain. Une phrase captée à côté après des minutes de
      silence part au cerveau avec la marque du doute (Décision 44), sans
      accusé de réception de la surface.
    - Engagé : la forme décide. Question, relance courte, phrase brève, ou
      consigne à l'impératif / à la deuxième personne (« Regarde dans mon
      Drive… », quelle qu'en soit la longueur) : adressé. Une longue phrase à
      la troisième personne reste incertaine — c'est la forme typique d'une
      conversation voisine.
    """

    FOLLOWUPS = ("oui", "non", "yes", "no", "ok", "d'accord", "et ", "mais ", "alors ", "continue", "pourquoi", "comment", "quand", "où", "qui", "quoi")

    def classify(self, text: str, *, active: bool, engaged: bool | None = None) -> AddressingDecision:
        normalized = " ".join(text.casefold().strip().split())
        if not normalized:
            return AddressingDecision.AMBIENT
        if normalized.startswith("jarvis") or mentions_jarvis(text):
            return AddressingDecision.ADDRESSED
        if not active:
            return AddressingDecision.AMBIENT
        if engaged is False:
            return AddressingDecision.UNCERTAIN
        if normalized.endswith("?") or normalized.startswith(self.FOLLOWUPS) or len(normalized.split()) <= 8:
            return AddressingDecision.ADDRESSED
        if engaged and looks_like_request(text):
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

    Capture en duplex (mode continu) : avec un `CaptureProcessor`, chaque bloc
    du micro passe par l'annulation d'écho et la garde d'écho *dans le thread
    PortAudio*, avant d'atteindre la file d'envoi ; chaque bloc joué lui est
    remis comme référence juste après son écriture, hors de `_output_lock`. Les
    signaux de parole proche remontent sur la boucle par `on_capture_signal`.
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
        capture: "CaptureProcessor | None" = None,
    ) -> None:
        self.input_device = input_device
        self.output_device = output_device
        # Traitement duplex du micro (mode continu) ; absent, le micro part tel
        # quel, exactement comme avant.
        self.capture = capture
        # Appelé sur la boucle asyncio pour chaque signal de la capture
        # (`jarvis.audio.duplex.NEAR_END`). Posé par le bridge.
        self.on_capture_signal: Callable[[str], object] | None = None
        # Gain appliqué aux blocs suivants : le barge-in baisse la voix de
        # JARVIS dès que l'utilisateur semble parler, avant de la couper.
        self._output_gain = 1.0
        self._applied_gain = 1.0
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
        # Un drapeau par bloc en file, dans le même ordre : dit lequel porte le
        # rejeu du propriétaire, que la file n'a pas le droit d'évincer.
        self._queued_replay: deque[bool] = deque()
        #: Rejeux tout de même perdus (file saturée par un autre rejeu) : tracé.
        self.dropped_replays = 0
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
        # Début, dans la sortie, de l'élément audio en cours (voir
        # `set_active_output`).
        self._item_offset_bytes = 0
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
            raw = bytes(indata)
            capture = self.capture
            try:
                if capture is None:
                    loop.call_soon_threadsafe(self._enqueue, raw)
                else:
                    try:
                        processed, signals = capture.process(raw)
                    except Exception:
                        # Jamais d'exception dans le callback PortAudio : le
                        # micro repart brut plutôt que de faire tomber le flux.
                        processed, signals = raw, ()
                    loop.call_soon_threadsafe(self._deliver_capture, len(raw), processed, signals)
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

    def _deliver_capture(self, captured: int, processed: bytes, signals: tuple[str, ...]) -> None:
        """Remettre sur la boucle un bloc traité par la capture duplex."""

        self.captured_bytes += captured
        if processed:
            # Le bloc qui porte un rejeu contient un début de phrase que la
            # capture a déjà marqué envoyé (`_sent_until`) : personne ne le
            # réoffrira, la file n'a donc pas le droit de l'évincer.
            if self._put_input(processed, replay=OWNER_REPLAY_SIGNAL in signals):
                signals = (*signals, OWNER_REPLAY_DROPPED_SIGNAL)
        callback = self.on_capture_signal
        if callback is not None:
            for signal in signals:
                callback(signal)

    # -- garde d'écho : état lu par le bridge ---------------------------------

    @property
    def echo_guard_open(self) -> bool:
        """Le fournisseur entend-il le micro ? Toujours vrai sans capture duplex."""

        return self.capture is None or self.capture.gate_open

    @property
    def has_echo_guard(self) -> bool:
        return self.capture is not None

    @property
    def far_end_recent(self) -> bool:
        """JARVIS parle, ou vient de se taire (écho encore possible dans la pièce)."""

        return self.capture is not None and self.capture.far_recent

    def release_near_end(self) -> None:
        """Refermer la garde : la parole locale n'a pas été confirmée."""

        if self.capture is not None:
            self.capture.release_near_end()

    # -- Solo Owner : flux ouvert par le propriétaire (tâche 06) -------------

    @property
    def owner_gate_supported(self) -> bool:
        """La capture connaît-elle la garde du propriétaire ? (sans dire si elle l'accepte)."""

        return getattr(self.capture, "set_owner_gate", None) is not None

    def set_owner_gate(self, enabled: bool) -> bool:
        """Confier la garde de la capture au propriétaire ; False si elle ne sait pas rejouer."""

        setter = getattr(self.capture, "set_owner_gate", None)
        if setter is None:
            return False
        return bool(setter(enabled))

    def open_owner_flow(self, owner_onset_ms: int, *, candidate_onset_ms: int | None = None) -> None:
        """Rejouer le préfixe non envoyé du propriétaire, puis le direct (voir `CaptureProcessor`).

        Le rejeu suit le chemin de tout bloc capturé — `_deliver_capture`,
        file d'envoi, `pump_input` — jamais la lecture : il part derrière ce
        qui a déjà été envoyé, devant le direct.
        """

        opener = getattr(self.capture, "open_owner_flow", None)
        if opener is not None:
            opener(owner_onset_ms, candidate_onset_ms=candidate_onset_ms)

    def close_owner_flow(self) -> None:
        closer = getattr(self.capture, "close_owner_flow", None)
        if closer is not None:
            closer()

    def take_owner_replays(self) -> tuple[object, ...]:
        take = getattr(self.capture, "take_owner_replays", None)
        return tuple(take()) if take is not None else ()

    def set_output_gain(self, gain: float) -> None:
        """Gain des prochains blocs joués (1.0 = normal)."""

        self._output_gain = max(0.0, min(1.0, float(gain)))

    def _apply_gain(self, block: bytes) -> bytes:
        """Appliquer le gain courant, en rampe sur le bloc pour éviter un clic."""

        target, start = self._output_gain, self._applied_gain
        self._applied_gain = target
        if target == 1.0 and start == 1.0:
            return block
        import numpy as np

        samples = np.frombuffer(block, dtype=np.int16).astype(np.float32)
        ramp = np.linspace(start, target, num=len(samples), dtype=np.float32) if start != target else target
        return np.clip(samples * ramp, -32768, 32767).astype(np.int16).tobytes()

    def _enqueue(self, raw: bytes) -> None:
        self.captured_bytes += len(raw)
        self._put_input(raw)

    def _put_input(self, raw: bytes, *, replay: bool = False) -> bool:
        """Mettre un bloc capté en file d'envoi ; rend True si un rejeu a été perdu.

        File pleine (envoi fournisseur bloqué) : on écarte le plus ancien, comme
        avant — sauf si c'est un rejeu du propriétaire. Celui-là ne peut pas être
        réoffert, alors on écarte plutôt le bloc en direct qui arrive : mieux
        vaut perdre la fin d'une phrase que son début (tâche 06).
        """

        if self._queue.full():
            if self._queued_replay and self._queued_replay[0] and not replay:
                return False
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            else:
                if self._queued_replay and self._queued_replay.popleft():
                    # Deux rejeux coincés derrière un envoi bloqué : très
                    # improbable, mais jamais silencieux (spec §3).
                    self.dropped_replays += 1
                    self._queue.put_nowait(raw)
                    self._queued_replay.append(replay)
                    return True
        self._queue.put_nowait(raw)
        self._queued_replay.append(replay)
        return False

    async def pump_input(self, session: RealtimeSession) -> None:
        while True:
            raw = await self._queue.get()
            if self._queued_replay:
                self._queued_replay.popleft()
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
        self._queued_replay.append(False)

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

        Une même réponse peut porter plusieurs éléments audio — le modèle a
        par exemple ajouté un préambule avant le texte à lire. La troncature
        vise un élément et se compte depuis *son* début : quand l'élément change
        au sein d'une sortie, on retient où il commence.
        """

        identity = output_id or speech_id
        with self._cursor_lock:
            current = self._output_id or self._output_speech_id
            if identity and identity != current:
                self._output_epoch += 1
                self._playback_epoch += 1
                self._output_written_bytes = 0
                self._item_offset_bytes = 0
                self._output_speech_id = speech_id or None
                self._output_id = output_id or None
                self._output_response_id = response_id or None
                self._output_item_id = item_id or None
                self._output_latency_ms = self._stream_latency_ms()
                return
            self._output_speech_id = self._output_speech_id or speech_id or None
            self._output_id = self._output_id or output_id or None
            self._output_response_id = self._output_response_id or response_id or None
            if item_id and self._output_item_id and item_id != self._output_item_id:
                # Élément suivant de la même réponse : il commence ici.
                self._item_offset_bytes = self._output_written_bytes
                self._output_item_id = item_id
            else:
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
            item_start_ms = self._item_offset_bytes * 1000.0 / (self.output_sample_rate * self._BYTES_PER_FRAME)
            return PlaybackCursor(
                speech_id=speech_id,
                played_ms=max(0, int(self._played_ms_locked() - item_start_ms)),
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
        # Époques figées sur la boucle, *avant* de passer au thread : si un
        # `stop_output()` survient entre-temps, le thread doit voir que ce bloc
        # appartient au passé. Les lire au démarrage du thread laissait jouer
        # un bloc entier après la coupure.
        with self._cursor_lock:
            epochs = (self._output_epoch, self._playback_epoch)
        await asyncio.to_thread(self._write_output, base64.b64decode(value), epochs)

    def _write_output(self, pcm: bytes, epochs: tuple[int, int] | None = None) -> None:
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
        if epochs is None:
            with self._cursor_lock:
                epochs = (self._output_epoch, self._playback_epoch)
        epoch, playback_epoch = epochs
        capture = self.capture
        for offset in range(0, len(pcm), step):
            block = self._apply_gain(pcm[offset:offset + step])
            with self._output_lock:
                stream = self._output
                if stream is None or self._closing or playback_epoch != self._playback_epoch:
                    return
                stream.write(block)
            self._credit_written(epoch, len(block))
            if capture is not None and playback_epoch == self._playback_epoch:
                # Ce qui vient d'entrer dans le tampon du périphérique sera
                # entendu, donc renverra de l'écho : l'annuleur doit le savoir.
                # Coupé entre-temps, `abort()` l'a jeté : il ne sera jamais
                # entendu, et le compter ferait croire que JARVIS parle encore.
                capture.push_reference(block)

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
        if self.capture is not None:
            # `abort()` a jeté le tampon : cette référence ne sera jamais
            # entendue, la garder ferait croire que JARVIS parle encore.
            self.capture.clear_reference()
        # La prochaine sortie repart à plein volume.
        self._output_gain = 1.0

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

    Micro ouvert pendant que les haut-parleurs jouent : en mode continu, la
    capture passe par `jarvis.audio.duplex` (annulation d'écho, garde d'écho),
    et les transcripts par `jarvis.runtime.turn_filters` (écho, bruit). Le mode
    legacy reste le repli half-duplex.

    Trois tâches pendant `_consume`, une seule boucle asyncio :

    - le **lecteur** vide le flux du fournisseur sans jamais attendre ;
    - la **lecture** joue l'audio dans l'ordre reçu, et ne remet les
      évènements de fin de sortie (`ORDERED_OUTPUT_EVENTS`) qu'une fois
      l'audio qui les précède réellement joué ;
    - la tâche **principale** traite tout le reste, dès réception.

    C'est ce qui rend le barge-in possible : le fournisseur génère plus vite
    que le temps réel, donc quand l'utilisateur coupe JARVIS, `speech_started`
    arrive alors que des secondes d'audio attendent encore d'être jouées.
    Jouer l'audio dans la boucle principale, comme avant, faisait attendre
    `speech_started` derrière toute la phrase : JARVIS ne s'arrêtait jamais.
    Tous les rappels du runtime (`on_mute` compris) restent appelés par la
    tâche principale — jamais par la lecture, que `mute()` annulerait sous ses
    propres pieds.

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
        on_idle: Callable[[], object] | None = None,
        on_thinking: Callable[[], object] | None = None,
        on_speaking: Callable[[], object] | None = None,
        on_response_done: Callable[[], object] | None = None,
        on_output_event: Callable[[ProtocolEnvelope], object] | None = None,
        on_interruption: Callable[[PlaybackCursor | None], object] | None = None,
        on_user_speech: Callable[[bool], object] | None = None,
        on_reflex: Callable[..., object] | None = None,
        auto_turn: bool = False,
        continuous: bool = False,
        classifier: ConservativeAddressingClassifier | None = None,
        journal: RuntimeJournal | None = None,
        claude=None,
        engagement_window_s: float = 30.0,
        barge_in_confirm_s: float = 0.8,
        barge_in_duck_gain: float = 0.3,
        clock: Callable[[], float] | None = None,
        barge_in_authority: BargeInAuthority = BargeInAuthority.ACOUSTIC,
        owner_source: "OwnerStateSource | None" = None,
        on_authorization_refused: Callable[[str, str], object] | None = None,
    ) -> None:
        barge_in_authority = BargeInAuthority(barge_in_authority)
        if barge_in_authority is BargeInAuthority.OWNER and (owner_source is None or not continuous):
            # Jamais d'autorité du propriétaire sans vérificateur pour la
            # porter : JARVIS deviendrait impossible à couper à la voix.
            raise ValueError("owner barge-in authority needs a continuous bridge and an owner-state source")
        self.core = core
        self.session = session
        self.conversation_id = conversation_id
        self.audio = audio
        self.on_addressed = on_addressed
        self.on_mute = on_mute
        self.on_ambient = on_ambient
        self.on_listening = on_listening
        # Veille de la surface. En continu, la session reste ACTIVE bien
        # au-delà de l'échange qui l'a ouverte : afficher « écoute » pendant
        # ce temps-là fait croire à l'utilisateur que JARVIS se déclenche pour
        # lui à chaque phrase prononcée dans la pièce. Tant que rien ne lui a
        # été adressé (voir `_rest_surface`), l'écran revient à cette veille.
        # Absent : l'ancien comportement, tout retour se fait sur `on_listening`.
        self.on_idle = on_idle
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

        # -- mode continu : tours, écho, barge-in -----------------------------
        # Prévient l'ordonnanceur que l'utilisateur parle (VAD serveur) : il ne
        # lance pas une phrase par-dessus lui.
        self.on_user_speech = on_user_speech
        # Demande d'accusé de réception à l'ordonnanceur, après un tour adressé.
        self.on_reflex = on_reflex
        self._clock = clock or time.monotonic
        self.engagement_window_s = engagement_window_s
        self.barge_in_confirm_s = barge_in_confirm_s
        self.barge_in_duck_gain = barge_in_duck_gain
        # Le réveil vaut engagement : la première phrase après F9 est adressée.
        self._last_engaged = self._clock()
        self._echo = EchoGuard(clock=self._clock)
        self._recent_reflexes: deque[str] = deque(maxlen=4)
        self._user_speaking = False
        self._last_playback_end = float("-inf")
        # Segment VAD capté pendant une parole de JARVIS (ou juste après) :
        # seul un tel segment peut être de l'écho. Par élément fournisseur,
        # parce que le transcript arrive après le segment suivant parfois.
        self._segment_near_playback: dict[str, bool] = {}
        self._last_segment_near_playback = False
        # Barge-in en deux temps : la capture locale entend l'utilisateur, la
        # voix de JARVIS baisse ; le VAD du fournisseur confirme, elle se tait.
        self._barge_pending_token = 0
        self._barge_pending = False
        # Le candidat en attente a-t-il baissé la voix ? Toujours en salle
        # ouverte, jamais en Solo Owner (voir `_note_owner_candidate`).
        self._barge_pending_ducked = False
        # -- Solo Owner : autorité du propriétaire (voir `BargeInAuthority`) --
        self.barge_in_authority = barge_in_authority
        self._owner_source = owner_source if barge_in_authority is BargeInAuthority.OWNER else None
        # Boucle qui reçoit les états du fil du vérificateur, posée par
        # `_consume` le temps de l'abonnement.
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._owner_attached = False
        # Dernier état de l'autorité effective, pour ne tracer que ses changements.
        self._owner_ready: bool | None = None
        # Dernier état du propriétaire accepté : un état qui n'est pas plus
        # récent (séquence) ou qui vient d'une session antérieure est écarté.
        self._owner_session = 0
        self._owner_sequence = 0
        # Corrélation avec le VAD du fournisseur (diagnostic seulement) : son
        # dernier `speech_started` pendant que JARVIS parlait sans propriétaire
        # confirmé, et la dernière coupure du propriétaire pas encore corrélée.
        self._provider_speech_at: float | None = None
        self._owner_stopped_at: float | None = None
        # Tâche 06 : la capture a-t-elle accepté de confier sa garde au
        # propriétaire (tampon de rejeu présent) ? Sans cela, la garde reste
        # acoustique, comme en tâche 05.
        self._owner_gated = False
        # Dernière ouverture du flux demandée, pour dater son rejeu, et
        # instant de capture du dernier arrêt local du propriétaire.
        self._owner_replay_context: dict[str, object] | None = None
        self._owner_stop_stream_ms: int | None = None
        self._last_replay_ms: int | None = None
        # -- Solo Owner : entrée filtrée par l'identité (tâche 07) ------------
        # Le runtime est prévenu quand Solo Owner se referme en cours de
        # session (alerte visible, état lu par le Control Center).
        self.on_authorization_refused = on_authorization_refused
        # Flux du propriétaire ouvert vers le fournisseur, et dernier instant
        # (horloge du bridge) où il l'était : un segment du VAD fournisseur
        # n'est attribué au propriétaire que s'il commence pendant, ou peu
        # après — le fournisseur segmente le rejeu avec un temps de retard.
        self._owner_flow_open = False
        self._owner_forwarded_at: float | None = None
        self._segment_owner: dict[str, bool] = {}
        self._last_segment_owner = False
        # L'ordonnanceur est-il tenu par un candidat local (voix pas encore
        # jugée, ou propriétaire reconnu) ? Voir `_hold_for_candidate`.
        self._local_speech = False
        # Dernier état remis à l'ordonnanceur (VAD fournisseur ou candidat local).
        self._notified_speech = False
        # Solo Owner refermé faute de vérificateur : une seule fois par session.
        self._owner_lost = False
        # Traces d'entrée écartée côté fournisseur, bornées par minute.
        self._drop_traces: deque[float] = deque()
        self._drops_suppressed = 0
        # Plomberie de `_consume` (voir la docstring de la classe).
        self._inbox: asyncio.Queue | None = None
        self._playout: asyncio.Queue | None = None
        self._seq = 0
        self._queued_audio = 0
        self._drop_audio_before = 0
        self._unfinished = 0
        self._idle = asyncio.Event()
        self._idle.set()
        # Sorties reçues du fournisseur et pas encore finies de jouer ici, par
        # identité (voir `_output_identity`). Tenues par le lecteur, retirées
        # quand la fin de la sortie est traitée.
        self._received_outputs: dict[str, dict[str, object]] = {}
        self._last_correlation_id: str | None = None
        # Dernier envoi d'une annulation ou d'une troncature (barge-in).
        self._control_sent_at = float("-inf")

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
            self._received_outputs.pop(identity, None)
        output_id = _optional_text((event.payload or {}).get("output_id"))
        if output_id is not None:
            self._audio_notified_outputs.discard(output_id)

    async def _barge_in(self, *, owner: OwnerStateSnapshot | None = None) -> None:
        """Interrompre JARVIS parce que l'utilisateur parle (spec §12, mode continu).

        Ordre imposé, et c'est tout l'intérêt de la méthode : l'arrêt local
        d'abord, le fournisseur ensuite. `stop_output()` ne fait qu'un aller
        vers PortAudio, donc l'utilisateur cesse d'entendre JARVIS sans attendre
        le moindre aller-retour réseau ; l'annulation et la troncature ne
        partent qu'après, une fois le curseur figé.

        Rien n'est annulé côté travail : couper la parole n'est pas annuler la
        tâche (Décisions 15 et 35). Le tour utilisateur qui suit portera
        simplement `interrupted_speech_id`, et c'est le cerveau qui décidera.

        C'est le mécanisme d'arrêt ; ce qui le déclenche relève de la
        politique (`BargeInAuthority`). `owner` : l'état du propriétaire qui a
        autorisé la coupure en Solo Owner, pour dater l'arrêt sur l'horloge de
        la capture ; absent, rien ne change à la trace d'avant.
        """

        started = time.perf_counter()
        # Tout l'audio déjà reçu et pas encore joué appartient à ce qui vient
        # d'être coupé : la tâche de lecture le jettera au lieu de le jouer.
        self._drop_audio_before = self._seq
        self._barge_pending = False
        self._barge_pending_token += 1
        self._last_engaged = self._clock()
        await self.audio.stop_output()
        stop_stream_ms = self._capture_stream_ms() if owner is not None else None
        if owner is not None:
            self._owner_stop_stream_ms = stop_stream_ms
        interrupted = self._live_output_identity
        # Le curseur de l'audio décrit la dernière sortie *jouée*. Si plus rien
        # ne jouait (la sortie coupée n'avait encore rien fait entendre), il
        # désignerait une phrase déjà entendue en entier : pas de curseur.
        cursor = self.audio.playback_cursor() if interrupted is not None else None
        stop_latency_ms = round((time.perf_counter() - started) * 1000, 1)
        # Toute sortie reçue et pas finie est coupée, pas seulement celle qui
        # jouait : une sortie dont aucun bloc n'est encore sorti enverrait
        # sinon la suite de sa phrase après la parole de l'utilisateur.
        targets = set(self._received_outputs)
        if interrupted is not None:
            targets.add(interrupted)
        self._interrupted_outputs.update(targets)
        for identity, entry in self._received_outputs.items():
            heard = 0.0
            if cursor is not None and identity == interrupted and float(entry.get("audio_ms") or 0) > 0:
                heard = min(1.0, cursor.played_ms / float(entry["audio_ms"]))
            # L'écho possible ne porte que sur ce qui a été entendu.
            self._echo.limit(identity, heard)
        self._playing = False
        self._live_output_identity = None
        if cursor is not None:
            self._interrupted_speech_id = cursor.speech_id
        else:
            newest = next(reversed(self._received_outputs.values()), None)
            self._interrupted_speech_id = (
                _optional_text(newest.get("speech_id")) or _optional_text(newest.get("output_id")) if newest else None
            )
        await self._call_with(self.on_interruption, cursor)
        data: dict[str, object] = {
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
        }
        if owner is not None:
            data["trigger"] = BargeInAuthority.OWNER.value
        self._trace("voice.barge_in", "L'utilisateur a coupé la parole de JARVIS", data=data)
        if owner is not None:
            self._trace_owner_stop(owner, stop_stream_ms=stop_stream_ms, data=data)
        await self._cancel_provider_output(cursor)

    def _capture_stream_ms(self) -> int | None:
        """Instant présent sur l'horloge de la capture duplex, s'il y en a une."""

        value = getattr(getattr(self.audio, "capture", None), "stream_ms", None)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def _trace_owner_stop(self, owner: OwnerStateSnapshot, *, stop_stream_ms: int | None, data: dict[str, object]) -> None:
        """Dater une coupure du propriétaire : début de parole → confirmation → arrêt local.

        Tout sur l'horloge de la capture (millisecondes d'audio capté depuis le
        début de la session), la même que celle de l'état du propriétaire :
        les écarts ne dépendent ni du retard du fil du vérificateur ni de celui
        de la boucle. `stop_latency_ms`, lui, mesure l'appel d'arrêt local.
        Le fournisseur n'y figure qu'en corrélation : avait-il déjà signalé la
        parole, et depuis combien de temps.
        """

        now = self._clock()
        lead, self._provider_speech_at = self._provider_speech_at, None
        self._owner_stopped_at = now
        if lead is not None and now - lead > self.OWNER_ADVISORY_WINDOW_S:
            lead = None
        onset, confirmed = owner.owner_onset_ms, owner.confirmed_ms

        def gap(start: int | None, end: int | None) -> int | None:
            # Horloges incohérentes (session changée entre-temps) : pas de chiffre.
            return end - start if start is not None and end is not None and end >= start else None

        self._trace(
            BARGE_IN_OWNER_CONFIRMED_KIND,
            "Propriétaire reconnu pendant que JARVIS parlait : sortie coupée localement",
            data={
                "conversation_id": self.conversation_id,
                "session": owner.session,
                "sequence": owner.sequence,
                "candidate_onset_ms": owner.candidate_onset_ms,
                "owner_onset_ms": onset,
                "confirmed_ms": confirmed,
                "stop_stream_ms": stop_stream_ms,
                "confirm_ms": gap(onset, confirmed),
                "confirm_to_stop_ms": gap(confirmed, stop_stream_ms),
                "onset_to_stop_ms": gap(onset, stop_stream_ms),
                "stop_latency_ms": data.get("stop_latency_ms"),
                "owner_score": owner.owner_score,
                "evidence_ms": owner.evidence_ms,
                "speech_id": data.get("speech_id"),
                "output_id": data.get("output_id"),
                "played_ms": data.get("played_ms"),
                "provider_speech_started": lead is not None,
                "provider_lead_ms": round((now - lead) * 1000) if lead is not None else None,
            },
        )

    async def _cancel_provider_output(self, cursor: PlaybackCursor | None) -> None:
        """Annuler la génération, puis aligner l'historique du fournisseur.

        Aucune des deux étapes n'est vitale pour que le son s'arrête — c'est
        déjà fait. Un échec dégrade donc le tour (le modèle croira avoir dit
        plus que ce qui a été entendu) sans jamais casser la session vocale.

        Sans curseur, il n'y a rien à tronquer : une pile qui n'émet pas
        d'identifiant de sortie (Gemini Live, Décision 21) traverse ce chemin
        sans exception.
        """

        # Les réponses du fournisseur à ces deux commandes arrivent plus tard
        # dans le flux : une erreur qui les suit de près est la leur.
        self._control_sent_at = self._clock()
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
        self._last_correlation_id = correlation_id
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

    # -- boucle d'évènements ----------------------------------------------------

    async def wait_idle(self) -> None:
        """Attendre que tout ce qui a été reçu du fournisseur soit traité.

        Audio joué compris. Les tests, qui injectent leurs évènements d'un bloc,
        s'en servent pour retrouver l'enchaînement du temps réel.
        """

        await self._idle.wait()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _begin_item(self) -> None:
        self._unfinished += 1
        self._idle.clear()

    def _finish_item(self) -> None:
        self._unfinished = max(0, self._unfinished - 1)
        if self._unfinished == 0:
            self._idle.set()

    def _post(self, kind: str, item: object = None) -> None:
        """Déposer un signal local dans la boîte de la tâche principale."""

        inbox = self._inbox
        if inbox is None:
            return
        self._begin_item()
        inbox.put_nowait((kind, item, None))

    def _on_capture_signal(self, signal: str) -> None:
        """Rappel de la capture duplex, appelé sur la boucle asyncio."""

        if signal == NEAR_END_SIGNAL:
            self._post("near_end")
        elif signal == OWNER_REPLAY_SIGNAL:
            self._post("owner_replay")
        elif signal == OWNER_REPLAY_DROPPED_SIGNAL:
            self._post("owner_replay_dropped")

    def _dispatch(self, event: ProtocolEnvelope) -> None:
        """Aiguiller un évènement fournisseur dès réception, sans jamais attendre."""

        assert self._inbox is not None and self._playout is not None
        self._begin_item()
        message_type = event.message_type
        payload = event.payload or {}
        if message_type in {"realtime.audio", "realtime.output_started"}:
            self._note_output_received(payload, audio=message_type == "realtime.audio")
        if message_type == "realtime.audio":
            self._queued_audio += 1
            self._enqueue_playout("audio", event)
        elif message_type in ORDERED_OUTPUT_EVENTS:
            if message_type == "realtime.assistant_transcript":
                # Retenu dès réception : l'écho de cette phrase peut revenir au
                # micro avant qu'elle ait fini de jouer.
                self._echo.remember(str(payload.get("text") or ""), key=self._output_identity(payload))
            self._enqueue_playout("event", event)
        elif self.continuous and self._queued_audio > 0:
            # De l'audio reçu avant cet évènement n'est pas encore joué : il
            # passe devant, sinon la parole de l'utilisateur attendrait la fin
            # de la phrase qu'elle doit couper. Le legacy, half-duplex, n'a
            # rien à couper : il garde l'ordre strict du flux.
            self._inbox.put_nowait(("urgent", event, None))
        else:
            # Rien ne joue : l'ordre du flux est respecté à la lettre.
            self._enqueue_playout("event", event)

    def _enqueue_playout(self, kind: str, item: object) -> None:
        assert self._playout is not None
        self._playout.put_nowait((self._next_seq(), kind, item))

    def _note_output_received(self, payload: dict[str, object], *, audio: bool) -> None:
        """Tenir, dès réception, les sorties que le fournisseur a commencées.

        La lecture ne les découvre qu'en les jouant : un barge-in qui survient
        entre-temps doit pourtant pouvoir couper une sortie dont aucun bloc
        n'est encore sorti, et mettre ses blocs à venir sur liste noire.
        """

        identity = self._output_identity(payload)
        if identity is None:
            return
        entry = self._received_outputs.setdefault(
            identity,
            {"output_id": _optional_text(payload.get("output_id")), "speech_id": _optional_text(payload.get("speech_id")), "audio_ms": 0.0},
        )
        if audio:
            # Taille décodée d'un base64 : 3 octets pour 4 caractères, int16 mono.
            size = len(str(payload.get("pcm_b64") or "")) * 3 // 4
            rate = int(getattr(self.audio, "output_sample_rate", 24000) or 24000)
            entry["audio_ms"] = float(entry["audio_ms"]) + size * 1000.0 / (rate * 2)
        while len(self._received_outputs) > 32:
            self._received_outputs.pop(next(iter(self._received_outputs)))

    def output_pending(self, output_id: str) -> bool:
        """Une sortie reçue n'a-t-elle pas encore fini d'être jouée ici ?

        Lu par l'ordonnanceur : le fournisseur a fini de *générer* bien avant
        que le haut-parleur ait fini de *jouer*, et seul le bridge le sait.
        """

        return any(entry.get("output_id") == output_id for entry in self._received_outputs.values())

    async def _read_provider(self, events) -> None:  # noqa: ANN001
        """Tâche de lecture du flux fournisseur.

        La fin du flux et une connexion perdue passent par la file de lecture :
        elles ne sont traitées qu'une fois l'audio déjà reçu joué, comme avant.
        Toute autre panne remonte aussitôt à la tâche principale.
        """

        assert self._inbox is not None and self._playout is not None
        try:
            async for event in events:
                self._dispatch(event)
        except ConnectionError as exc:
            self._begin_item()
            self._enqueue_playout("disconnected", exc)
        except Exception as exc:
            self._begin_item()
            self._inbox.put_nowait(("failed", exc, None))
        else:
            self._begin_item()
            self._enqueue_playout("end", None)

    async def _play_out(self) -> None:
        """Tâche de lecture : l'audio dans l'ordre, puis ce qui le suivait."""

        assert self._inbox is not None and self._playout is not None
        while True:
            seq, kind, item = await self._playout.get()
            if kind == "audio":
                try:
                    await self._play_audio(seq, item)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._post("failed", exc)
                    return
                finally:
                    self._queued_audio = max(0, self._queued_audio - 1)
                    self._finish_item()
                continue
            # Évènement ordonné : la tâche principale le traite, et la lecture
            # attend qu'elle ait fini — l'état qu'il pose (`_playing`, curseur)
            # doit précéder l'audio de la sortie suivante.
            done = asyncio.Event()
            self._inbox.put_nowait((kind, item, done))
            await done.wait()
            if kind in {"end", "disconnected"}:
                return

    async def _play_audio(self, seq: int, event: ProtocolEnvelope) -> None:
        self._response_had_audio = True
        if seq <= self._drop_audio_before or self._output_was_interrupted(event.payload):
            # Reçu avant le barge-in, ou encore émis par le fournisseur pour la
            # phrase coupée : le jouer remettrait du son après que
            # l'utilisateur a repris la parole, et le créditer fausserait la
            # troncature.
            return
        self._track_playback_output(event)
        await self._note_first_audio(event)
        await self._call(self.on_speaking)
        await self.audio.play_b64(str(event.payload.get("pcm_b64") or ""))

    async def _consume(self, events) -> None:  # noqa: ANN001
        """Traiter le flux du fournisseur.

        Une connexion perdue est une fin de vie normale, pas une panne : le
        websocket Realtime peut être fermé pendant qu'un outil lent travaille.
        Laisser l'exception remonter tuait tout le processus Voice alors que le
        tour venait de réussir.

        Voir la docstring de la classe pour le partage entre les trois tâches.
        """

        self._inbox, self._playout = asyncio.Queue(), asyncio.Queue()
        self._unfinished = 0
        self._idle.set()
        detach_owner = self._attach_owner_source()
        reader = asyncio.create_task(self._read_provider(events), name="jarvis-realtime-reader")
        player = asyncio.create_task(self._play_out(), name="jarvis-realtime-playout")
        try:
            while True:
                kind, item, done = await self._inbox.get()
                try:
                    if kind == "end":
                        return
                    if kind == "disconnected":
                        await self._note_disconnected(item)
                        return
                    if kind == "failed":
                        raise item
                    if kind == "near_end":
                        await self._on_near_end()
                    elif kind == "barge_timeout":
                        await self._on_barge_timeout(item)
                    elif kind == "owner_state":
                        await self._on_owner_state(item)
                    elif kind == "owner_replay":
                        self._on_owner_replay()
                    elif kind == "owner_replay_dropped":
                        self._on_owner_replay_dropped()
                    elif kind == "owner_lost":
                        await self._on_owner_lost(item)
                        return
                    elif await self._handle_event(item):
                        return
                except ConnectionError as exc:
                    # Écrire sur un websocket qui se ferme (résultat d'outil,
                    # annulation) : même fin de vie qu'une lecture coupée.
                    await self._note_disconnected(exc)
                    return
                finally:
                    if done is not None:
                        done.set()
                    self._finish_item()
        finally:
            self._detach_owner_source(detach_owner)
            for task in (reader, player):
                task.cancel()
            await asyncio.gather(reader, player, return_exceptions=True)
            self._inbox = self._playout = None
            self._unfinished = 0
            self._queued_audio = 0
            self._idle.set()

    async def _note_disconnected(self, exc: object) -> None:
        self._trace(
            "provider.disconnected",
            f"Connexion Realtime perdue: {exc}",
            level="warning",
            data={"code": "realtime_disconnected", "conversation_id": self.conversation_id},
        )
        await self._rescue_undelivered_answer()

    # -- barge-in en deux temps ----------------------------------------------

    def _output_live(self) -> bool:
        """JARVIS parle, ou a reçu de l'audio qu'il n'a pas encore joué."""

        return self._playing or self._queued_audio > 0

    def _set_output_gain(self, gain: float) -> None:
        setter = getattr(self.audio, "set_output_gain", None)
        if setter is not None:
            setter(gain)

    def _barge_in_allowed(self) -> bool:
        """Le VAD du fournisseur a-t-il pu entendre autre chose que l'écho ?

        Sans garde d'écho (pile de test, capture brute), il n'y a pas d'autre
        témoin : on le croit, comme avant. Avec la garde, le fournisseur ne
        reçoit le micro pendant que JARVIS parle que si la capture locale a
        entendu l'utilisateur ; un `speech_started` garde fermée ne peut venir
        que de ce qui a précédé la fermeture, ou de l'écho.
        """

        if not getattr(self.audio, "has_echo_guard", False):
            return True
        return bool(getattr(self.audio, "echo_guard_open", True)) or self._barge_pending

    async def _on_near_end(self) -> None:
        """La capture locale entend l'utilisateur pendant que JARVIS parle.

        Premier temps du barge-in : la voix de JARVIS baisse aussitôt, et la
        garde s'est ouverte pour que le fournisseur entende la phrase depuis son
        début. Le second temps — couper — attend que le VAD du fournisseur
        confirme qu'il s'agit bien de parole : un choc sur le bureau ou une
        toux ne doivent pas faire taire JARVIS. Sans confirmation dans
        `barge_in_confirm_s`, la voix remonte et la garde se referme.

        Autorité acoustique (salle ouverte) seulement. En Solo Owner, la
        parole proche ne baisse ni ne coupe rien : voir `_note_owner_candidate`.
        """

        if not self.continuous or not self._output_live():
            return
        if self.barge_in_authority is BargeInAuthority.OWNER:
            # Solo Owner configuré : jamais la règle acoustique, même
            # vérificateur perdu — l'entrée est alors refermée (tâche 07).
            if self._owner_authority():
                self._note_owner_candidate()
            return
        if self._user_speaking:
            # Le VAD du fournisseur est déjà en parole : c'est confirmé.
            await self._barge_in()
            return
        if self._barge_pending:
            return
        self._barge_pending = True
        self._barge_pending_ducked = True
        self._barge_pending_token += 1
        token = self._barge_pending_token
        self._set_output_gain(self.barge_in_duck_gain)
        self._trace(
            "voice.barge_in_pending",
            "Parole détectée localement pendant que JARVIS parle : voix baissée, confirmation attendue",
            data={"conversation_id": self.conversation_id},
        )
        asyncio.get_running_loop().call_later(self.barge_in_confirm_s, self._post, "barge_timeout", token)

    async def _on_barge_timeout(self, token: object) -> None:
        if not self._barge_pending or token != self._barge_pending_token:
            return
        if self._owner_gated and self._owner_authority() and self._owner_state_value() not in (None, OwnerState.IDLE.value):
            # Solo Owner, garde au propriétaire (tâche 06) : le fournisseur
            # n'entend plus rien pendant que JARVIS parle, son silence ne
            # prouve donc pas l'écho. Le candidat du vérificateur est toujours
            # ouvert : parole soutenue, le verrou reste — comme après un
            # `speech_started` en tâche 05. Relâcher maintenant ferait monter
            # le couplage au niveau de cette voix, et rendrait le détecteur
            # sourd au propriétaire. Le verrou tombe quand le candidat se
            # ferme, sur une fenêtre qui ne contient plus que l'écho.
            asyncio.get_running_loop().call_later(self.barge_in_confirm_s, self._post, "barge_timeout", token)
            return
        self._barge_pending = False
        if self._barge_pending_ducked:
            self._set_output_gain(1.0)
        release = getattr(self.audio, "release_near_end", None)
        if release is not None:
            release()
        if self._barge_pending_ducked:
            self._trace(
                "voice.barge_in_rejected",
                "Parole locale non confirmée par le fournisseur : JARVIS reprend à plein volume",
                data={"conversation_id": self.conversation_id, "code": "barge_in_not_confirmed"},
            )
        else:
            self._trace(
                "voice.barge_in_rejected",
                "Parole locale non confirmée par le fournisseur : garde d'écho refermée, volume jamais baissé",
                data={
                    "conversation_id": self.conversation_id,
                    "code": "barge_in_not_confirmed",
                    "authority": BargeInAuthority.OWNER.value,
                },
            )

    # -- Solo Owner : la confirmation du propriétaire coupe (tâche 05) --------

    #: Fenêtre de corrélation entre une coupure du propriétaire et le
    #: `speech_started` du fournisseur qui la précède ou la suit.
    OWNER_ADVISORY_WINDOW_S = 5.0

    def _owner_authority(self) -> bool:
        """La confirmation du propriétaire gouverne-t-elle le barge-in en ce moment ?

        Vrai seulement si l'autorité `OWNER` a été choisie à l'activation
        **et** que le vérificateur est abonné et prêt. Un vérificateur tombé
        en panne pendant la session ne peut plus reconnaître personne. Solo
        Owner se referme alors en sécurité (tâche 07, `_lose_owner`) : la
        garde reste au propriétaire, flux fermé — plus rien de ce que capte le
        micro n'atteint le fournisseur —, c'est tracé, et la session se
        désactive en disant pourquoi. Jamais de repli silencieux sur la salle
        ouverte.
        """

        if self.barge_in_authority is not BargeInAuthority.OWNER:
            return False
        availability: str | None = None
        ready = False
        if self._owner_attached:
            try:
                availability = VerifierAvailability(getattr(self._owner_source, "availability")).value
                ready = availability == VerifierAvailability.READY.value
            except Exception:
                ready = False
        if ready is not self._owner_ready:
            previous, self._owner_ready = self._owner_ready, ready
            if not ready:
                self._lose_owner("owner_verifier_unavailable", availability=availability)
            elif previous is not None:
                self._trace(
                    BARGE_IN_AUTHORITY_KIND,
                    "Vérificateur de locuteur de nouveau prêt : seul le propriétaire coupe JARVIS",
                    data={
                        "conversation_id": self.conversation_id,
                        "configured": BargeInAuthority.OWNER.value,
                        "authority": BargeInAuthority.OWNER.value,
                        "availability": availability,
                        "code": "owner_verifier_ready",
                    },
                )
        return ready

    #: Message du refus en cours de session (tâche 07) : ce qui s'est passé,
    #: ce qui est garanti, et comment en sortir.
    OWNER_LOST_MESSAGE = (
        "Mode Solo Owner suspendu : le vérificateur de locuteur ne répond plus. Par sécurité, plus rien "
        "de ce que capte le micro n'est transmis, et la session vocale se désactive. Réveillez JARVIS "
        "pour réessayer ; si cela se répète, repassez conversation_mode sur open_room et relancez Voice."
    )

    def _lose_owner(self, code: str, *, availability: str | None = None, error: str | None = None) -> None:
        """Fermeture sûre de Solo Owner en cours de session (tâche 07).

        Synchrone, appelable de partout sur la boucle : l'entrée se referme
        tout de suite — garde au propriétaire, flux fermé —, puis la tâche
        principale désactive la session (`_on_owner_lost`).
        """

        if self._owner_lost:
            return
        self._owner_lost = True
        self._set_owner_gate(True)
        if self._owner_gated:
            self._close_owner_flow()
        data: dict[str, object] = {
            "conversation_id": self.conversation_id,
            "configured": BargeInAuthority.OWNER.value,
            "authority": BargeInAuthority.OWNER.value,
            "input": "closed",
            "availability": availability,
            "code": code,
        }
        if error is not None:
            data["error"] = error
        self._trace(
            BARGE_IN_AUTHORITY_KIND,
            "Vérificateur de locuteur indisponible : Solo Owner refermé par sécurité, plus rien n'atteint "
            "le fournisseur ; la session se désactive",
            level="warning",
            data=data,
        )
        self._post("owner_lost", data)

    async def _on_owner_lost(self, data: object) -> None:
        """Tâche principale : dire pourquoi, puis désactiver la session comme un « Jarvis mute »."""

        details = dict(data) if isinstance(data, dict) else {}
        code = str(details.get("code") or "owner_verifier_unavailable")
        message = self.OWNER_LOST_MESSAGE
        self._trace(
            AUTHORIZATION_REFUSED_KIND,
            message,
            level="warning",
            data={
                "conversation_id": self.conversation_id,
                "phase": "session",
                "conversation_mode": "solo_owner",
                "availability": details.get("availability"),
                "code": code,
            },
        )
        callback = self.on_authorization_refused
        if callback is not None:
            value = callback(code, message)
            if hasattr(value, "__await__"):
                await value
        await self._call(self.on_mute)

    def _attach_owner_source(self) -> Callable[[], None] | None:
        """S'abonner à l'état du propriétaire pour la durée de `_consume`.

        L'état courant sert de référence : ce qui a été publié avant ce bridge
        (session précédente, confirmation déjà ancienne) ne coupera rien.
        La garde de la capture est confiée au propriétaire d'emblée, flux
        fermé (tâche 07) : rien ne part avant qu'il ne soit reconnu.
        """

        source = self._owner_source
        if source is None:
            return None
        # Posé avant la garde : une capture qui la refuse ici doit refermer
        # l'entrée (`_set_owner_gate`), pas laisser Solo Owner se dégrader.
        self._owner_attached = True
        self._set_owner_gate(True)
        self._owner_loop = asyncio.get_running_loop()
        try:
            baseline = source.owner_state
            self._owner_session, self._owner_sequence = int(baseline.session), int(baseline.sequence)
            detach = source.add_owner_listener(self._owner_listener)
        except Exception as exc:
            self._owner_attached = False
            self._owner_loop = None
            self._owner_ready = False
            self._lose_owner("owner_listener_unavailable", error=type(exc).__name__)
            return None
        # État initial de l'autorité : rien à dire s'il est prêt.
        self._owner_authority()
        return detach

    def _detach_owner_source(self, detach: Callable[[], None] | None) -> None:
        self._owner_attached = False
        self._owner_loop = None
        if self._owner_gated:
            # La garde reste au propriétaire jusqu'à la remise à zéro de la
            # capture : rendre la main à la règle acoustique maintenant
            # laisserait passer le micro brut le temps que la session se
            # referme (tâche 07).
            self._close_owner_flow()
        if detach is None:
            return
        try:
            detach()
        except Exception:
            # Désabonnement best effort : la session vocale se ferme de toute façon.
            pass

    def _owner_listener(self, snapshot: OwnerStateSnapshot) -> None:
        """Rappel du fil du vérificateur : passer la main à la boucle, rien d'autre.

        Jamais d'exception ici — le publieur retirerait l'abonnement — et
        jamais d'appel en retour vers le vérificateur.
        """

        loop = self._owner_loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._post, "owner_state", snapshot)
        except RuntimeError:
            # La boucle se ferme : plus personne à prévenir.
            pass

    async def _on_owner_state(self, snapshot: object) -> None:
        """Nouvel état du propriétaire, sur la tâche principale (D05, D09).

        Le déclencheur Solo Owner : le propriétaire confirmé pendant que JARVIS
        est audible (`far_end`) et qu'une sortie non encore coupée joue ou
        attend. L'arrêt local part aussitôt, sans attendre le fournisseur ;
        annulation et troncature suivent en best effort (`_barge_in`).

        Écartés : un état périmé (séquence déjà vue) ou d'une session
        antérieure de la capture, une confirmation pendant que JARVIS se tait —
        il n'y a rien à couper, et ce n'est pas à ce bridge d'ouvrir un tour
        (tâche 07) —, et une confirmation qui suit une coupure déjà faite.

        Flux vers le fournisseur (tâche 06, garde au propriétaire) : toute
        confirmation ouvre le flux — après l'arrêt local et l'envoi de
        l'annulation et de la troncature s'il y a eu coupure, pour que
        l'historique du fournisseur soit aligné avant la parole qui suit. La
        capture rejoue alors, une fois, le préfixe jamais envoyé depuis
        `owner_onset_ms`, puis le direct. Un verdict « étranger » ou la fin du
        candidat referment le flux : que JARVIS parle ou se taise (tâche 07),
        le fournisseur n'entend plus que du silence. Une réponse brève
        reconnue à la fin de son candidat arrive en `owner_confirmed` puis
        `idle` : la capture rejoue tout le candidat, puis referme.

        Un état qui arrive alors que le vérificateur n'est plus prêt referme
        Solo Owner (`_owner_authority`), sans rien ouvrir.
        """

        if not isinstance(snapshot, OwnerStateSnapshot):
            return
        if snapshot.session < self._owner_session or snapshot.sequence <= self._owner_sequence:
            return
        self._owner_session, self._owner_sequence = snapshot.session, snapshot.sequence
        if not self.continuous or not self._owner_authority():
            return
        await self._hold_for_candidate(snapshot.state)
        if snapshot.state is OwnerState.OWNER_CONFIRMED:
            cut = snapshot.far_end and self._interruptible_output()
            if cut:
                await self._barge_in(owner=snapshot)
            self._open_owner_flow(snapshot, cut=cut)
        elif snapshot.state in (OwnerState.IDLE, OwnerState.REJECTED) and self._owner_gated:
            self._close_owner_flow()

    async def _hold_for_candidate(self, state: OwnerState) -> None:
        """Solo Owner : l'ordonnanceur ne lance rien par-dessus une voix pas encore jugée (D14).

        Un candidat acoustique encore sans verdict peut être le propriétaire,
        pas encore reconnu (≈ 1,5 à 2 s) : un accusé ou une réponse lancés
        maintenant lui parleraient par-dessus. Il tient donc l'ordonnanceur
        (`on_user_speech`), comme le VAD du fournisseur en salle ouverte ; le
        propriétaire reconnu aussi. Un verdict « étranger » ou la fin du
        candidat le libèrent : une autre voix ne retient JARVIS que le temps
        d'être jugée, jamais indéfiniment — et ne crée ni accusé ni tour. Elle
        peut en revanche faire tomber un accusé en attente, comme toute prise
        de parole (l'accusé est facultatif, parler sur le propriétaire ne l'est
        pas).
        """

        speaking = state in (OwnerState.CANDIDATE, OwnerState.OWNER_CONFIRMED)
        if speaking is self._local_speech:
            return
        self._local_speech = speaking
        await self._notify_user_speech()

    #: Après la fermeture du flux du propriétaire, délai pendant lequel un
    #: nouveau segment du VAD fournisseur lui est encore attribué : le rejeu
    #: part d'un bloc, le fournisseur le segmente avec retard, et une réponse
    #: brève est rejouée et refermée d'un seul geste.
    OWNER_SEGMENT_GRACE_S = 3.0
    #: Traces `voice.input.non_owner_dropped` du bridge par minute, au plus.
    MAX_DROP_TRACES_PER_MINUTE = 30

    def _input_gated(self) -> bool:
        """Solo Owner avec garde au propriétaire : seul le flux qu'il ouvre atteint le fournisseur."""

        return self.continuous and self.barge_in_authority is BargeInAuthority.OWNER and self._owner_gated

    def _admit_provider_segment(self, item_id: str | None) -> bool:
        """Un `speech_started` du fournisseur vient-il du flux du propriétaire ?

        Défense en profondeur (tâche 07) : la capture ne transmet déjà rien
        d'autre, le fournisseur ne devrait donc rien segmenter d'autre. Ce
        qui commence hors du flux ouvert — et de son court délai — est écarté
        et tracé ; la décision est retenue pour le transcript du segment.
        """

        at = self._owner_forwarded_at
        admitted = self._owner_flow_open or (at is not None and self._clock() - at <= self.OWNER_SEGMENT_GRACE_S)
        self._last_segment_owner = admitted
        if item_id:
            self._segment_owner[item_id] = admitted
            while len(self._segment_owner) > 16:
                self._segment_owner.pop(next(iter(self._segment_owner)))
        if not admitted:
            self._drop_input("provider_speech_unverified")
        return admitted

    def _segment_from_owner(self, item_id: str | None) -> bool:
        if item_id and item_id in self._segment_owner:
            return self._segment_owner.pop(item_id)
        return self._last_segment_owner

    def _drop_input(self, reason: str) -> None:
        """Tracer une entrée écartée côté fournisseur : raison seule, jamais le texte ni l'audio."""

        now = self._clock()
        sent = self._drop_traces
        while sent and now - sent[0] >= 60.0:
            sent.popleft()
        if len(sent) >= self.MAX_DROP_TRACES_PER_MINUTE:
            self._drops_suppressed += 1
            return
        sent.append(now)
        data: dict[str, object] = {
            "conversation_id": self.conversation_id,
            "mode": "enforce",
            "source": "provider",
            "reason": reason,
            "code": f"input_{reason}",
        }
        if self._drops_suppressed:
            data["suppressed"] = self._drops_suppressed
            self._drops_suppressed = 0
        self._trace(
            INPUT_NON_OWNER_DROPPED_KIND,
            "Entrée écartée : ce segment ne vient pas du flux ouvert par le propriétaire",
            data=data,
        )

    def _close_owner_flow(self) -> None:
        """Refermer le flux du propriétaire vers le fournisseur (silence à la place du micro)."""

        if self._owner_flow_open:
            self._owner_flow_open = False
            self._owner_forwarded_at = self._clock()
        close = getattr(self.audio, "close_owner_flow", None)
        if close is not None:
            close()

    def _set_owner_gate(self, enabled: bool) -> None:
        """Confier (ou reprendre) la garde de la capture au propriétaire ; retenir si elle l'a acceptée."""

        setter = getattr(self.audio, "set_owner_gate", None)
        accepted = False
        if setter is not None:
            try:
                accepted = bool(setter(enabled))
            except Exception:
                accepted = False
        self._owner_gated = enabled and accepted
        if (
            enabled
            and not accepted
            and self._owner_attached
            and self.barge_in_authority is BargeInAuthority.OWNER
            and getattr(self.audio, "owner_gate_supported", False)
        ):
            # Spec §3 : jamais de repli silencieux. Sans la garde, Solo Owner
            # deviendrait « le propriétaire coupe, mais tout le monde est
            # transmis » ; on referme plutôt l'entrée, comme pour un
            # vérificateur perdu. L'activation refuse déjà une capture sans
            # tampon de rejeu (`solo_owner_capture_unsupported`) : ce cas-ci est
            # celui d'une capture duplex qui se dérobe à l'ouverture de la
            # session.
            self._lose_owner("solo_owner_capture_unsupported")

    def _open_owner_flow(self, snapshot: OwnerStateSnapshot, *, cut: bool) -> None:
        """Demander à la capture le rejeu du préfixe du propriétaire, puis le direct."""

        if not self._owner_gated or snapshot.owner_onset_ms is None:
            return
        self._owner_replay_context = {
            "session": snapshot.session,
            "sequence": snapshot.sequence,
            "candidate_onset_ms": snapshot.candidate_onset_ms,
            "owner_onset_ms": snapshot.owner_onset_ms,
            "confirmed_ms": snapshot.confirmed_ms,
            "stop_stream_ms": self._owner_stop_stream_ms if cut else None,
            "barge_in": cut,
        }
        self._owner_flow_open = True
        self._owner_forwarded_at = self._clock()
        self.audio.open_owner_flow(  # type: ignore[attr-defined]
            snapshot.owner_onset_ms, candidate_onset_ms=snapshot.candidate_onset_ms
        )

    def _on_owner_replay(self) -> None:
        """La capture a rejoué un préfixe du propriétaire : le dater (`voice.owner.replay`).

        Scalaires seulement, horloge de la capture : début estimé, confirmation,
        arrêt local, début et durée du rejeu, et ce qui n'a pas été rejoué —
        déjà envoyé, ou plus ancien que le tampon (`clamped_ms`, avertissement).
        Un rejeu vide hors coupure (tout était déjà parti) n'est pas tracé.
        Depuis la tâche 07, JARVIS silencieux, le fournisseur n'a rien reçu
        avant la confirmation : chaque tour du propriétaire a son rejeu.
        """

        take = getattr(self.audio, "take_owner_replays", None)
        if take is None:
            return
        context, self._owner_replay_context = self._owner_replay_context, None
        for replay in take():
            replay_ms = int(getattr(replay, "replay_ms", 0))
            clamped_ms = int(getattr(replay, "clamped_ms", 0))
            onset = getattr(replay, "owner_onset_ms", None)
            until = getattr(replay, "until_ms", None)
            matched = context if context is not None and context.get("owner_onset_ms") == onset else {}
            self._last_replay_ms = replay_ms
            if not (replay_ms or clamped_ms or matched.get("barge_in")):
                continue
            confirmed = matched.get("confirmed_ms")
            data: dict[str, object] = {
                "conversation_id": self.conversation_id,
                "session": matched.get("session"),
                "sequence": matched.get("sequence"),
                "candidate_onset_ms": matched.get("candidate_onset_ms"),
                "owner_onset_ms": onset,
                "confirmed_ms": confirmed,
                "stop_stream_ms": matched.get("stop_stream_ms"),
                "barge_in": bool(matched.get("barge_in")),
                "requested_from_ms": getattr(replay, "requested_from_ms", None),
                "replay_from_ms": getattr(replay, "from_ms", None),
                "replay_until_ms": until,
                "replay_ms": replay_ms,
                "margin_ms": getattr(replay, "margin_ms", None),
                "already_sent_ms": getattr(replay, "already_sent_ms", None),
                "clamped_ms": clamped_ms,
                "buffer_ms": getattr(replay, "buffer_ms", None),
                "confirm_to_replay_ms": until - confirmed
                if isinstance(until, int) and isinstance(confirmed, int) and until >= confirmed
                else None,
            }
            if clamped_ms:
                data["code"] = "owner_replay_clamped"
            self._trace(
                OWNER_REPLAY_KIND,
                "Début de phrase du propriétaire plus ancien que le tampon : rejeu tronqué"
                if clamped_ms
                else "Début de phrase du propriétaire rejoué vers le fournisseur, puis le direct",
                level="warning" if clamped_ms else "info",
                data=data,
            )

    def _on_owner_replay_dropped(self) -> None:
        """La file d'envoi a perdu un rejeu : le dire, jamais un succès muet (spec §3)."""

        self._trace(
            OWNER_REPLAY_KIND,
            "Rejeu du propriétaire perdu : la file d'envoi au fournisseur était saturée, ce début de "
            "phrase ne lui parviendra pas",
            level="warning",
            data={
                "conversation_id": self.conversation_id,
                "code": "owner_replay_dropped",
                "dropped_replays": int(getattr(self.audio, "dropped_replays", 0)),
            },
        )

    def _interruptible_output(self) -> bool:
        """Reste-t-il une sortie audible, ou reçue et à venir, qui n'a pas été coupée ?

        `_output_live()` reste vrai après une coupure tant que la lecture n'a
        pas jeté les blocs reçus avant elle : sur ce seul critère, un second
        signal couperait deux fois. Ici, seul compte ce qui n'est ni sous la
        marque de coupure ni sur la liste noire des sorties interrompues.
        """

        if self._playing:
            return True
        if self._queued_audio <= 0 or self._seq <= self._drop_audio_before:
            return False
        if not self._received_outputs:
            # Pile sans identifiant de sortie : l'audio reçu après la marque
            # de coupure ne peut appartenir qu'à une sortie nouvelle.
            return True
        return any(identity not in self._interrupted_outputs for identity in self._received_outputs)

    def _note_owner_candidate(self) -> None:
        """Solo Owner : la parole proche n'est qu'un candidat acoustique (D03, D04).

        Ni baisse de volume ni coupure : une conversation de bureau continue
        ferait sinon onduler la voix de JARVIS, et une autre voix n'a pas le
        droit de l'interrompre. Seule la confirmation du propriétaire coupe
        (`_on_owner_state`).

        Le délai de confirmation acoustique reste celui de la salle ouverte :
        sans `speech_started` du fournisseur dans `barge_in_confirm_s`, la
        garde se referme et le détecteur apprend l'écho (`release_near_end`).
        Avec lui, c'est bien de la parole : la garde reste ouverte, pour que le
        fournisseur entende la phrase depuis son début si c'est le propriétaire.

        Garde au propriétaire (tâche 06, capture avec tampon de rejeu) : le
        verrou n'ouvre plus rien, le fournisseur n'entend pas cette voix. Le
        délai ne relâche le verrou qu'une fois le candidat du vérificateur
        refermé (`_on_barge_timeout`) ; le début de phrase du propriétaire
        part au rejeu (`_open_owner_flow`).
        """

        if self._user_speaking or self._barge_pending:
            return
        self._barge_pending = True
        self._barge_pending_ducked = False
        self._barge_pending_token += 1
        token = self._barge_pending_token
        self._trace(
            "voice.barge_in_pending",
            "Parole détectée localement pendant que JARVIS parle : identité en vérification, volume inchangé",
            data={"conversation_id": self.conversation_id, "authority": BargeInAuthority.OWNER.value},
        )
        asyncio.get_running_loop().call_later(self.barge_in_confirm_s, self._post, "barge_timeout", token)

    def _owner_state_value(self) -> str | None:
        try:
            return OwnerState(self._owner_source.owner_state.state).value  # type: ignore[union-attr]
        except Exception:
            return None

    def _note_provider_speech(self, *, jarvis_audible: bool) -> None:
        """Solo Owner : le `speech_started` du fournisseur corrèle, il ne coupe jamais (D09).

        Le VAD du fournisseur entend toute voix que la garde laisse passer —
        une autre personne aussi bien que le propriétaire en cours de
        vérification. Il ne décide donc rien, qu'il arrive avant, après ou
        jamais :

        - JARVIS audible, aucun propriétaire confirmé : JARVIS continue. Le
          signal vaut confirmation acoustique (de la parole, pas de l'écho) :
          le délai de `_note_owner_candidate` ne refermera pas la garde. Il est
          retenu pour dater l'avance du fournisseur si le propriétaire est
          confirmé ensuite ;
        - juste après une coupure du propriétaire : le fournisseur rattrape la
          décision locale ; son retard est mesuré, rien n'est recoupé.

        La trace `voice.barge_in.provider_advisory` ne porte que des scalaires.
        """

        now = self._clock()
        data: dict[str, object] = {
            "conversation_id": self.conversation_id,
            "owner_state": self._owner_state_value(),
            "guard_open": bool(getattr(self.audio, "echo_guard_open", True)),
        }
        if jarvis_audible and self._interruptible_output():
            self._provider_speech_at = now
            if self._barge_pending:
                self._barge_pending = False
                self._barge_pending_token += 1
            data["relation"] = "awaiting_owner"
            message = "Début de parole signalé par le fournisseur, aucun propriétaire confirmé : JARVIS continue"
        else:
            stopped = self._owner_stopped_at
            if stopped is None or now - stopped > self.OWNER_ADVISORY_WINDOW_S:
                return
            self._owner_stopped_at = None
            data["relation"] = "after_owner_stop"
            data["lag_ms"] = round((now - stopped) * 1000)
            # Garde au propriétaire : le fournisseur n'a pu entendre que le
            # rejeu, ce début de parole le segmente (tâche 06).
            data["replay_ms"] = self._last_replay_ms
            message = "Début de parole signalé par le fournisseur après l'arrêt local : corrélé, rien à recouper"
        self._trace(BARGE_IN_PROVIDER_ADVISORY_KIND, message, data=data)

    def _engaged(self) -> bool:
        """L'utilisateur est-il en conversation avec JARVIS en ce moment ?"""

        if self.engagement_window_s <= 0:
            return True
        return self._clock() - self._last_engaged <= self.engagement_window_s

    async def _rest_surface(self) -> None:
        """L'état d'écran entre deux segments qui n'étaient pas pour JARVIS.

        Le micro reste ouvert — la session continue d'entendre, et un vrai
        réveil (touche, « Jarvis… ») passe toujours. Ce qui change est ce que
        l'utilisateur voit : hors conversation engagée, une phrase captée à
        côté ne doit pas allumer l'écoute, sans quoi JARVIS a l'air de se
        déclencher pour lui à chaque fois qu'on parle dans la pièce. Engagé
        (réveil récent, réponse de JARVIS, demande adressée il y a peu), on
        revient à l'écoute comme avant : l'utilisateur est en train de lui
        parler, et cacher l'écoute lui ferait croire qu'il n'est plus entendu.
        """

        if self.continuous and self.on_idle is not None and not self._engaged():
            await self._call(self.on_idle)
            return
        await self._call(self.on_listening)

    def _segment_was_near_playback(self, item_id: str | None) -> bool:
        if item_id and item_id in self._segment_near_playback:
            return self._segment_near_playback.pop(item_id)
        return self._last_segment_near_playback

    #: Après la fin d'une parole de JARVIS, un segment peut encore contenir son
    #: écho (réverbération, tampon du périphérique).
    ECHO_WINDOW_S = 2.0

    #: Une erreur du fournisseur reçue dans ce délai après une annulation ou
    #: une troncature est la réponse à cette commande, pas une panne.
    CONTROL_ERROR_WINDOW_S = 5.0

    async def _note_user_speech(self, active: bool) -> None:
        """Le VAD du fournisseur entend l'utilisateur, ou ne l'entend plus."""

        if self._user_speaking == active:
            return
        self._user_speaking = active
        await self._notify_user_speech()

    async def _notify_user_speech(self) -> None:
        """Prévenir l'ordonnanceur : VAD du fournisseur, ou candidat local en Solo Owner.

        En salle ouverte seul le VAD du fournisseur compte, exactement comme
        avant ; `_user_speaking` reste le sien (le barge-in le lit).
        """

        speaking = self._user_speaking or self._local_speech
        if speaking == self._notified_speech:
            return
        self._notified_speech = speaking
        await self._call_with(self.on_user_speech, speaking)

    async def _request_reflex(self, text: str) -> None:
        """Proposer un accusé de réception à l'ordonnanceur, qui décidera s'il sert.

        Il ne partira que si le cerveau tarde : une réponse rapide rend
        l'accusé inutile, et l'ordonnanceur le jette alors.
        """

        if self.on_reflex is None or self._last_correlation_id is None:
            return
        if len(words(text)) < REFLEX_MIN_WORDS:
            return
        value = self.on_reflex(text, correlation_id=self._last_correlation_id, avoid=tuple(self._recent_reflexes))
        if hasattr(value, "__await__"):
            await value

    # -- traitement d'un évènement -------------------------------------------

    async def _handle_event(self, event: ProtocolEnvelope) -> bool:
        """Traiter un évènement ; rend True quand la session doit s'arrêter."""

        if event.message_type == "realtime.audio_done":
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
            if not self._output_live():
                # Plus rien ne joue : fin de parole de JARVIS. Un barge-in en
                # attente n'a plus rien à couper, la voix suivante repart à
                # plein volume, et la conversation reste engagée.
                if self._barge_pending:
                    self._barge_pending = False
                    self._barge_pending_token += 1
                self._set_output_gain(1.0)
                if response_had_audio:
                    self._last_playback_end = self._clock()
                    self._last_engaged = self._last_playback_end
            # Avant tout traitement local : c'est la fin de cette sortie
            # qui libère l'ordonnanceur, y compris quand la réponse
            # s'arrête sur un appel d'outil.
            await self._notify_output(event)
            if self._tool_result_pending:
                # Cette réponse-ci s'arrête sur l'appel d'outil ; le tour
                # se terminera sur celle que le résultat vient de créer.
                self._tool_result_pending = False
                return False
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
                return False
            if response_had_audio:
                await self._call(self.on_response_done)
                return False
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
            payload = event.payload or {}
            if self._input_gated() and not self._admit_provider_segment(_optional_text(payload.get("item_id"))):
                # Solo Owner : le fournisseur n'a pu entendre que du silence
                # ou un reste d'avant la garde. Défense en profondeur — ni
                # parole utilisateur, ni mesure, ni barge-in.
                return False
            # Borne de départ de la mesure 1, posée avant toute
            # décision : que ce segment coupe la parole de JARVIS ou
            # ouvre un tour, le délai jusqu'au premier son rendu est le
            # même chiffre pour l'utilisateur.
            self._open_speech_segment()
            near_playback = (
                self._output_live()
                or bool(getattr(self.audio, "far_end_recent", False))
                or self._clock() - self._last_playback_end < self.ECHO_WINDOW_S
            )
            self._last_segment_near_playback = near_playback
            item_id = _optional_text(payload.get("item_id"))
            if item_id:
                self._segment_near_playback[item_id] = near_playback
                while len(self._segment_near_playback) > 16:
                    self._segment_near_playback.pop(next(iter(self._segment_near_playback)))
            if self.continuous:
                await self._note_user_speech(True)
            if self.continuous and self._output_live():
                if self.barge_in_authority is BargeInAuthority.OWNER:
                    # Solo Owner : seul le propriétaire confirmé localement
                    # coupe. Ce signal peut venir de n'importe quelle voix ;
                    # il corrèle, il ne coupe pas (D09) — et vérificateur
                    # perdu, il ne coupe pas davantage (tâche 07).
                    if self._owner_authority():
                        self._note_provider_speech(jarvis_audible=True)
                elif self._barge_in_allowed():
                    # Barge-in : JARVIS parle et l'utilisateur enchaîne. Le
                    # chemin legacy, half-duplex, ne peut pas se trouver
                    # dans cet état — il garde donc exactement sa trace.
                    await self._barge_in()
                else:
                    # Garde fermée : le fournisseur n'a entendu que du
                    # silence ou de l'écho. Couper JARVIS ici, c'est le
                    # laisser s'interrompre lui-même.
                    self._trace(
                        "voice.barge_in_ignored",
                        "Début de parole signalé alors que la garde d'écho était fermée : JARVIS continue",
                        data={"conversation_id": self.conversation_id, "code": "speech_started_behind_echo_guard"},
                    )
            elif self.continuous or (self.auto_turn and not self._input_submitted):
                if self.continuous and self._owner_stopped_at is not None and self._owner_authority():
                    # Le VAD du fournisseur rattrape une coupure du propriétaire.
                    self._note_provider_speech(jarvis_audible=False)
                self._trace(
                    "voice.speech_started",
                    "Speech detected by server VAD",
                    data={"conversation_id": self.conversation_id},
                )
        elif event.message_type == "realtime.speech_stopped":
            if self.continuous:
                await self._note_user_speech(False)
        elif event.message_type == "realtime.input_committed":
            if self.continuous:
                # Sans parole, pas de commit : si `speech_stopped` s'est
                # perdu, c'est ici que l'utilisateur a fini de parler.
                await self._note_user_speech(False)
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
                if self._engaged():
                    # Le commit du VAD ne dit rien de l'adressage : il tombe
                    # sur n'importe quelle phrase prononcée dans la pièce.
                    # Hors conversation engagée, afficher « traitement » ici
                    # fait croire à l'utilisateur que JARVIS s'est déclenché
                    # pour lui. On attend le classement du transcript, qui
                    # posera lui-même « thinking » si le tour était adressé.
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
            return await self._handle_transcript(event)
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
                    self._recent_reflexes.append(text)
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
            await self._handle_tool_call(event)
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
                return False
            if self._clock() - self._control_sent_at <= self.CONTROL_ERROR_WINDOW_S:
                # Refus d'une annulation ou d'une troncature que nous venons
                # d'envoyer (« Audio content of 4450ms is already shorter
                # than 23868ms », 11/09) : le son est déjà coupé, seul
                # l'historique du fournisseur reste approximatif. Voice ne
                # doit pas tomber pour ça.
                self._trace(
                    "voice.barge_in_degraded",
                    f"Commande d'interruption refusée par le fournisseur: {message}",
                    level="warning",
                    data={"conversation_id": self.conversation_id, "code": code},
                )
                return False
            if code in RECOVERABLE_PROVIDER_ERRORS:
                self._trace(
                    "voice.provider_refused",
                    f"Demande refusée par le fournisseur, session maintenue: {message}",
                    level="warning",
                    data={"conversation_id": self.conversation_id, "code": code},
                )
                return False
            self._trace("provider.error", message, level="error", data={"code": code})
            raise RuntimeError(f"Realtime provider error [{code}]: {message}")
        return False

    async def _handle_transcript(self, event: ProtocolEnvelope) -> bool:
        item_id = _optional_text(event.payload.get("item_id"))
        if self._input_gated() and not self._segment_from_owner(item_id):
            # Solo Owner : l'identité passe avant l'adressage, et jamais par
            # le texte. Un segment que le propriétaire n'a pas ouvert n'est
            # ni tracé (pas de texte au journal), ni tour, ni activité utile.
            self._drop_input("transcript_unverified")
            await self._call(self.on_ambient)
            await self._rest_surface()
            return False
        # Borne de départ de la mesure 2. Prise avant le classement
        # d'adressage : ce qui est chronométré est le chemin complet
        # « transcript complet → Core a accepté », décision de
        # surface comprise.
        self._latency.mark(LATENCY_BRAIN_TURN_ACCEPTED, self.conversation_id)
        text = str(event.payload.get("text") or "").strip()
        near_playback = self._segment_was_near_playback(item_id)
        engaged = self._engaged() if self.continuous else None
        decision = self.classifier.classify(text, active=True, engaged=engaged)
        self._trace("voice.transcript", text or "<empty>", data={"addressing": decision.value})
        if self.continuous and text:
            reason = noise_reason(text)
            if reason is None and near_playback and self._echo.is_echo(text):
                reason = "echo"
            if reason is not None:
                # Ce n'est pas un propos de l'utilisateur : ni tour, ni
                # réarmement du délai, et l'écran revient à l'écoute.
                self._latency.forget(LATENCY_BRAIN_TURN_ACCEPTED, self.conversation_id)
                self._trace(
                    "voice.transcript_dropped",
                    text[:300],
                    data={
                        "conversation_id": self.conversation_id,
                        "reason": reason,
                        "near_playback": near_playback,
                        "code": f"transcript_{reason}",
                    },
                )
                await self._call(self.on_ambient)
                await self._rest_surface()
                return False
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
            # ni `on_addressed` ne sont appelés, ni aucun accusé de
            # réception : la surface ne doit pas afficher qu'elle
            # travaille pour l'utilisateur sur une phrase qui ne lui
            # était peut-être pas adressée.
            #
            # « Jarvis mute » ne peut pas tomber ici : toute phrase
            # mentionnant « jarvis » est classée ADDRESSED, donc
            # la commande reste traitée plus bas, avant tout envoi
            # au cerveau, exactement comme avant.
            await self._call(self.on_ambient)
            await self._submit_brain_turn(
                text,
                provider_item_id=item_id,
                addressing=decision,
            )
            await self._rest_surface()
            return False
        if decision is not AddressingDecision.ADDRESSED:
            # Entendu, mais pas pour JARVIS : le délai d'activité
            # utile ne bouge pas (Décision 10). AMBIENT est jeté
            # dans les deux modes ; UNCERTAIN ne parvient ici qu'en
            # legacy, où la surface possède les outils et garde son
            # rôle d'arbitre (Décisions 20 et 44).
            await self._call(self.on_ambient)
            if self.continuous:
                # Segment sans parole : plus rien ne ramènerait l'écran de
                # « thinking » (posé au commit) vers l'écoute — ou vers la
                # veille, si rien n'a été adressé à JARVIS depuis un moment.
                await self._rest_surface()
            return False
        normalized = " ".join(text.casefold().replace(",", " ").split())
        # La ponctuation de transcription ne change pas la commande vocale.
        # Garder toutes les lettres (y compris non latines) et les mots en
        # plus : une négation ou une mention de la commande n'est pas un mute.
        mute_words = "".join(
            " " if unicodedata.category(char).startswith("P") else char
            for char in text.casefold()
        ).split()
        if mute_words == ["jarvis", "mute"]:
            await self._call(self.on_mute)
            return True
        if self.continuous:
            # Chemin autoritaire unique : persistance et dépêche du
            # cerveau en une seule opération côté Core.
            submitted = await self._submit_brain_turn(text, provider_item_id=item_id)
            self._last_engaged = self._clock()
        else:
            submitted = False
            await self._append_legacy_user_turn(text)
        if self.continuous and not submitted:
            # Core a refusé le tour : aucune réponse ne viendra.
            await self._call(self.on_listening)
            return False
        await self._call(self.on_thinking)
        if self._pending_action_id is not None and normalized in {"oui", "non", "yes", "no"}:
            result = await self.core.confirm_action(self._pending_action_id, text)
            if result.get("disposition") != "confirm":
                self._pending_action_id = None
            await self.session.send_context("Jarvis Core confirmation result: " + str(result))
        await self._call(self.on_addressed)
        if self.continuous:
            await self._request_reflex(text)
        return False

    async def _handle_tool_call(self, event: ProtocolEnvelope) -> None:
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
            return
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
        if hasattr(self.audio, "on_capture_signal"):
            # Parole proche entendue par la capture duplex : premier temps du
            # barge-in (voir `_on_near_end`).
            self.audio.on_capture_signal = self._on_capture_signal
        if self.barge_in_authority is BargeInAuthority.OWNER:
            # Solo Owner (tâche 07) : la garde est au propriétaire dès le
            # premier bloc capté, flux fermé — pas un seul bloc brut ne part
            # avant l'abonnement à son état.
            self._set_owner_gate(True)
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
