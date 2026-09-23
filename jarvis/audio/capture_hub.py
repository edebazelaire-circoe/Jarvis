"""Capture partagée de PRESENTATION : un seul micro, plusieurs abonnés bornés.

Le problème que ce module existe pour résoudre, tel qu'il se pose dans ce
dépôt aujourd'hui : **trois** morceaux de code veulent le micro en même temps.

- `SoundDeviceRealtimeAudio` ouvre son propre `sd.RawInputStream` pour le
  chemin interactif ;
- `PorcupineWakeWordBackend` ouvre **le sien**, séparément, et le referme
  pendant une session active ;
- le mode PRESENTATION voudrait, lui, écouter la salle en continu.

En SIMPLE cela fonctionne parce que les deux premiers ne sont jamais ouverts en
même temps : Porcupine se suspend quand la session s'active. En PRESENTATION
rien ne se suspend — JARVIS écoute tout le temps — et deux flux concurrents sur
le même périphérique, c'est soit un refus du pilote, soit deux captures
dégradées. `docs/03-implementation-strategy.md` tranche : « Presentation
activation fails loudly if microphone ownership cannot be established; never
silently create two competing streams. »

Le hub est donc **le seul** propriétaire physique de l'entrée en PRESENTATION,
et tous les autres deviennent des abonnés.

Deux formes d'abonnement, et la différence est structurelle
------------------------------------------------------------

- **En ligne** (`sink=`) : le hub appelle l'abonné **dans le thread PortAudio**,
  sur le bloc brut, avant toute copie. C'est la forme dont le chemin interactif
  a besoin : `CaptureProcessor` fait l'annulation d'écho et la garde d'écho
  dans ce thread-là (`jarvis/audio/duplex.py`), et ce contrat est porteur — le
  déplacer sur la boucle casserait l'alignement de la référence. Un abonné en
  ligne doit accepter la fréquence du hub telle quelle : aucun
  rééchantillonnage n'a le droit d'entrer dans le thread audio.
- **En file** (défaut) : le bloc est déposé dans une file **bornée** propre à
  l'abonné, vidée sur la boucle asyncio par `blocks()`. C'est la forme des
  consommateurs lents ou périodiques — détecteur de mot d'éveil, segmentation
  ambiante de la Slice 06. Un abonné en file peut demander une autre fréquence :
  la conversion a lieu en le vidant, jamais dans le thread audio.

Contre-pression, et sa limite exacte
------------------------------------

Chaque file est bornée et **jamais bloquante**. Un abonné **en file** qui prend
du retard perd des blocs ; il ne ralentit ni le thread de capture ni les autres
abonnés. La politique est unique et fixe — **écarter le plus ancien**, la même
que `SoundDeviceRealtimeAudio._put_input` : quand la file déborde, ce qui vaut
encore quelque chose est le **présent**, pas un arriéré qu'on servirait ensuite
comme s'il était frais (la péremption que D06 interdit). Chaque perte est
comptée **et dite** par le surveillant ; rien ne disparaît sans un mot.

**Un abonné en ligne, lui, n'est pas isolé, et ne peut pas l'être.** Il
s'exécute *sur* le thread de capture ; un sink lent retarde mécaniquement tout
ce qui suit dans le même bloc, y compris les autres abonnés. C'est le prix de
l'annulation d'écho dans le thread audio, qui est un contrat porteur, et c'est
aussi la raison pour laquelle il n'existe qu'**un seul** abonné en ligne —
`attach_input`, le chemin interactif. La limite est mesurée par
`test_a_slow_inline_sink_starves_its_siblings_and_that_is_the_documented_limit`,
pour qu'elle soit connue plutôt que découverte.

Ce que la fermeture d'un abonné ne fait pas
--------------------------------------------

Fermer un abonnement détache l'abonné. Cela ne ferme **jamais** le flux
physique : c'est toute la différence avec le monde d'avant, où
`PorcupineWakeWordBackend.suspend()` fermait le périphérique. Seul
`AudioCaptureHub.close()` rend le micro.

Rien n'est persisté
-------------------

Le pré-roll et les files vivent dans des `deque` bornées en mémoire. Aucun octet
capturé ne touche le disque — la même ligne que `jarvis/audio/duplex.py` et
`jarvis/runtime/realtime_audio.py` tiennent déjà.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from enum import Enum
from typing import Protocol

from jarvis.audio.input_ownership import (
    OWNER_CAPTURE_HUB,
    open_input_stream_count,
    register_input_stream,
    release_input_stream,
)
from jarvis.audio.resampling import StreamingPcm16Resampler
from jarvis.ports.v2 import DiagnosticSink

_BYTES_PER_FRAME = 2  # int16 mono

#: Politique de contre-pression, unique et fixe : écarter le plus ancien. Une
#: seule règle, parce qu'aucun abonné n'a jamais eu besoin de l'autre et qu'un
#: paramètre que personne ne fait varier est du poids mort.
BACKPRESSURE_POLICY = "drop_oldest"

#: Durée du pré-roll gardé pour l'adresse explicite. D05 : en PRESENTATION
#: JARVIS écoute déjà, donc au moment où le mot d'éveil est reconnu, le début
#: de la phrase est **déjà passé**. Porcupine reconnaît « jarvis » entre 200 et
#: 400 ms après son attaque, et l'utilisateur enchaîne aussitôt ; 1500 ms
#: couvrent largement le mot lui-même et l'amorce de ce qui suit. Au-delà, on
#: ne garde plus un début de commande mais un morceau de conversation.
DEFAULT_PREROLL_MS = 1500
#: Plafond dur du pré-roll, quelle que soit la demande : la borne mémoire que
#: la revue peut vérifier sans lire l'appelant. 5 s à 24 kHz = 240 ko.
MAX_PREROLL_MS = 5000

#: Profondeur par défaut d'une file d'abonné, en blocs. Le hub capture par
#: blocs de 50 ms : 32 blocs = 1,6 s d'avance. Assez pour absorber une pause de
#: GC ou un appel modèle court, trop peu pour qu'un abonné bloqué accumule un
#: arriéré qu'il servirait ensuite comme s'il était frais.
DEFAULT_SUBSCRIBER_BLOCKS = 32
#: Plafond dur d'une file d'abonné : au-delà, ce n'est plus de la contre-pression
#: mais un tampon, et un tampon d'audio ambiant est exactement ce que D06
#: interdit (du contexte périmé servi comme frais).
MAX_SUBSCRIBER_BLOCKS = 128

#: Échecs rapprochés tolérés d'un abonné **en ligne** avant détachement, et la
#: fenêtre dans laquelle ils doivent se suivre pour compter comme une panne.
#:
#: Trois, parce qu'un abonné en ligne reçoit un bloc toutes les 50 ms : trois
#: échecs dans la fenêtre décrivent une panne qui dure, là où un ou deux
#: décrivent un accroc (une allocation qui rate, un verrou tenu un instant).
#: La **fenêtre** est ce qui rend le compteur honnête : sans elle, trois
#: accrocs isolés espacés d'une minute finiraient par détacher l'abonné, ce qui
#: est précisément le résultat que cette politique existe pour éviter. Deux
#: secondes valent quarante blocs — bien plus que n'importe quelle rafale
#: transitoire, bien moins qu'une pause d'inattention.
MAX_CONSECUTIVE_SINK_FAILURES = 3
SINK_FAILURE_WINDOW_S = 2.0

#: Sans un seul bloc pendant ce délai alors que le flux est ouvert, le
#: périphérique est considéré perdu. Le bridge interactif utilise déjà 2,5 s
#: pour `input_evidence_available` ; garder la même valeur évite deux vérités
#: sur « le micro répond-il encore ».
DEFAULT_SILENCE_TIMEOUT_S = 2.5
#: Période du surveillant. Assez lent pour ne rien coûter, assez rapide pour
#: qu'une perte de périphérique se dise en moins d'une seconde après le délai.
SUPERVISION_PERIOD_S = 0.25

#: Avis en attente gardés au plus, entre le thread de capture et la boucle. Un
#: abonné qui échoue à chaque bloc ne doit pas faire grossir une liste sans fin.
MAX_PENDING_NOTICES = 64

#: `paDeviceUnavailable` : le périphérique existe mais quelqu'un d'autre le
#: tient. C'est **la** panne que ce module doit nommer, pas diluer.
_PA_DEVICE_UNAVAILABLE = -9985


class CaptureHubState(str, Enum):
    IDLE = "idle"
    OPEN = "open"
    LOST = "lost"
    CLOSED = "closed"


class AudioCaptureHubError(RuntimeError):
    """Refus nommé du hub de capture (convention de la Slice 01).

    `code` est stable et anglais ; le message est lu par un humain francophone
    et **cite la panne réelle** plutôt que de la remplacer par une formule
    générique (`.claude/skills/error-handling`).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InputStreamFactory(Protocol):
    """Ouvrir un flux d'entrée. Injecté pour que les tests ne touchent jamais
    le vrai périphérique (`sounddevice` n'est importé que par le défaut)."""

    def __call__(
        self,
        *,
        samplerate: int,
        channels: int,
        dtype: str,
        device: object,
        blocksize: int,
        callback: Callable[..., None],
    ) -> object: ...


def sounddevice_input_stream(
    *,
    samplerate: int,
    channels: int,
    dtype: str,
    device: object,
    blocksize: int,
    callback: Callable[..., None],
) -> object:
    """Fabrique par défaut : le `RawInputStream` de sounddevice, démarré."""

    import sounddevice as sd  # type: ignore

    stream = sd.RawInputStream(
        samplerate=samplerate, channels=channels, dtype=dtype,
        device=device, blocksize=blocksize, callback=callback,
    )
    stream.start()
    return stream


class PreRollRing:
    """Anneau PCM borné, **en mémoire seulement**, pour l'adresse explicite.

    Borné deux fois, exprès : par la durée demandée et par le plafond dur
    `MAX_PREROLL_MS`. Les compteurs (`bytes_held`, `capacity_bytes`,
    `evicted_bytes`) sont publics pour qu'un test puisse constater la borne au
    lieu de la croire.
    """

    def __init__(self, *, sample_rate: int, preroll_ms: int) -> None:
        requested = max(0, int(preroll_ms))
        self.preroll_ms = min(requested, MAX_PREROLL_MS)
        self.clamped = requested > MAX_PREROLL_MS
        self.sample_rate = int(sample_rate)
        self.capacity_bytes = int(self.sample_rate * self.preroll_ms / 1000.0) * _BYTES_PER_FRAME
        self._blocks: deque[bytes] = deque()
        self.bytes_held = 0
        self.evicted_bytes = 0

    def append(self, block: bytes) -> None:
        if self.capacity_bytes <= 0 or not block:
            return
        self._blocks.append(block)
        self.bytes_held += len(block)
        while self.bytes_held > self.capacity_bytes and self._blocks:
            dropped = self._blocks.popleft()
            self.bytes_held -= len(dropped)
            self.evicted_bytes += len(dropped)

    def snapshot(self) -> bytes:
        """Copie des derniers octets captés. Jamais écrite nulle part."""

        return b"".join(self._blocks)

    def clear(self) -> None:
        """Vider l'anneau **et son histoire**.

        `evicted_bytes` repart de zéro : c'est ce qui alimente
        `CommandPreRoll.truncated`, et un anneau vide qui se déclarerait encore
        tronqué décrirait la séance précédente, pas celle-ci.
        """

        self._blocks.clear()
        self.bytes_held = 0
        self.evicted_bytes = 0


class CaptureSubscription:
    """Un abonné au PCM partagé. Borné, détachable, sans effet sur les autres.

    Ressemble volontairement à un flux `sounddevice` (`start()`, puis `stop()` /
    `close()` avec `ignore_errors`) : c'est ce qui permet à
    `SoundDeviceRealtimeAudio` de le traiter exactement comme le
    `RawInputStream` qu'il n'ouvre plus, sans une seule branche supplémentaire
    dans ses chemins de fermeture — **y compris la mise en route**. Un
    abonnement créé avec `start_paused` ne livre rien avant son `start()`,
    comme un vrai flux PortAudio, ce qui referme la fenêtre entre la création
    de l'abonnement et le démarrage effectif du bridge.
    """

    def __init__(
        self,
        hub: "AudioCaptureHub",
        *,
        name: str,
        sample_rate: int,
        max_blocks: int,
        sink: Callable[[bytes], None] | None,
        start_paused: bool = False,
    ) -> None:
        self._hub = hub
        self.name = name
        self.sample_rate = sample_rate
        self.max_blocks = max_blocks
        self.sink = sink
        self.inline = sink is not None
        self.started = not start_paused
        self._blocks: deque[bytes] = deque()
        self._event = asyncio.Event()
        self._resampler = (
            None if sample_rate == hub.sample_rate
            else StreamingPcm16Resampler(source_rate=hub.sample_rate, target_rate=sample_rate)
        )
        #: Comptabilité observable. Une contre-pression qu'on ne peut pas
        #: compter est une intention, pas une politique.
        self.delivered = 0
        self.dropped = 0
        self.failures = 0
        self.consecutive_failures = 0
        self._last_failure_at: float | None = None
        self.detached_reason: str | None = None
        self.closed = False

    # -- côté thread de capture -------------------------------------------

    def _offer(self, block: bytes) -> None:
        """Déposer un bloc. Appelé dans le thread PortAudio : ne bloque jamais,
        ne lève jamais, n'alloue rien d'illimité.

        Politique unique : file pleine, on écarte le **plus ancien**.
        """

        if len(self._blocks) >= self.max_blocks:
            self._blocks.popleft()
            self.dropped += 1
        self._blocks.append(block)
        self.delivered += 1

    # -- côté boucle asyncio ----------------------------------------------

    def _wake(self) -> None:
        self._event.set()

    async def blocks(self) -> AsyncIterator[bytes]:
        """Vider la file, à la fréquence demandée par cet abonné.

        C'est ici, sur la boucle, qu'a lieu le rééchantillonnage éventuel — et
        nulle part ailleurs : le thread audio n'en fait jamais.
        """

        if self.inline:
            raise AudioCaptureHubError(
                "capture_subscription_inline",
                f"L'abonné « {self.name} » est en ligne : il reçoit ses blocs par son sink, pas par blocks().",
            )
        while not self.closed:
            if self._blocks:
                block = self._blocks.popleft()
                if self._resampler is not None:
                    block = self._resampler.process(block)
                    if not block:
                        continue
                yield block
                continue
            self._event.clear()
            if self._blocks:
                # Un bloc est arrivé entre le test et le clear : ne pas dormir
                # dessus. (Aucun await entre les deux, donc aucune autre
                # tâche n'a pu s'intercaler ; seul le thread de capture a pu.)
                continue
            await self._event.wait()

    @property
    def pending(self) -> int:
        return len(self._blocks)

    def start(self, *, ignore_errors: bool = True) -> None:
        """Commencer à livrer. Sans objet pour un abonnement non mis en pause.

        Le pendant de `RawInputStream.start()` : un abonnement créé par
        `attach_input` reste muet jusqu'ici, de sorte que le chemin interactif
        ne reçoive pas de bloc avant d'avoir ouvert sa sortie — exactement la
        fenêtre qu'un vrai flux PortAudio n'a pas.
        """

        del ignore_errors
        self.started = True

    def stop(self, *, ignore_errors: bool = True) -> None:
        """Arrêter la livraison. Ne ferme **pas** le flux physique du hub."""

        del ignore_errors
        self.started = False
        self._blocks.clear()

    def close(self, *, ignore_errors: bool = True) -> None:
        """Se détacher du hub. Idempotent. Ne ferme **pas** le flux physique.

        Appelable **depuis n'importe quel thread** : sur le chemin partagé,
        `SoundDeviceRealtimeAudio._shutdown_stream` s'exécute dans un
        `asyncio.to_thread`, et `asyncio.Event.set()` n'est pas sûr hors de la
        boucle. Le réveil et le détachement sont donc renvoyés sur la boucle
        quand on n'y est pas.
        """

        del ignore_errors
        if self.closed:
            return
        self.closed = True
        self.started = False
        self._blocks.clear()
        self._hub._release_subscription(self)

    def stats(self) -> dict[str, object]:
        return {
            "name": self.name,
            "inline": self.inline,
            "started": self.started,
            "sample_rate": self.sample_rate,
            "policy": BACKPRESSURE_POLICY,
            "max_blocks": self.max_blocks,
            "pending": self.pending,
            "delivered": self.delivered,
            "dropped": self.dropped,
            "failures": self.failures,
            "detached_reason": self.detached_reason,
            "closed": self.closed,
        }


class AudioCaptureHub:
    """Le propriétaire physique unique de l'entrée, en mode PRESENTATION.

    Cycle de vie : `open()` puis `close()`, tous deux idempotents. Un hub fermé
    peut être rouvert — c'est le hub lui-même qui est rejouable, pas forcément
    la session qui l'enveloppe (voir `PresentationAudioSession`, dont les
    sources d'adresse ne se rouvrent pas et qui refuse donc un second départ).

    `open()` échoue **fort** : si le périphérique ne peut pas être pris, rien
    n'est à moitié ouvert, `open_input_streams` vaut 0, et l'appelant reçoit un
    `AudioCaptureHubError` nommé qui cite la panne réelle. C'est la règle de
    `docs/03-implementation-strategy.md` : jamais deux flux concurrents en
    silence.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 24000,
        block_frames: int = 1200,
        device: int | str | None = None,
        preroll_ms: int = DEFAULT_PREROLL_MS,
        stream_factory: InputStreamFactory | None = None,
        journal: DiagnosticSink | None = None,
        silence_timeout_s: float = DEFAULT_SILENCE_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        on_device_lost: Callable[[str], None] | None = None,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.block_frames = int(block_frames)
        self.device = device
        self.journal = journal
        self.clock = clock
        self.silence_timeout_s = max(0.1, float(silence_timeout_s))
        self.on_device_lost = on_device_lost
        self._stream_factory: InputStreamFactory = stream_factory or sounddevice_input_stream
        self.preroll = PreRollRing(sample_rate=self.sample_rate, preroll_ms=preroll_ms)
        self.state = CaptureHubState.IDLE
        self._stream: object | None = None
        self._subscriptions: list[CaptureSubscription] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._open_lock = asyncio.Lock()
        #: Avis produits dans le thread de capture, journalisés depuis la
        #: boucle. Le thread PortAudio n'écrit pas de fichier — même règle que
        #: `CaptureProcessor.take_alignments`.
        self._notices: deque[tuple[str, str, str, dict[str, object]]] = deque(maxlen=MAX_PENDING_NOTICES)
        self.blocks_captured = 0
        self.bytes_captured = 0
        self._last_block_at: float | None = None
        #: Pertes déjà dites, par abonné : le surveillant ne répète une ligne
        #: que lorsque le compte a bougé.
        self._reported_drops: dict[str, int] = {}

    # -- traces -----------------------------------------------------------

    def _trace(self, kind: str, message: str, *, level: str = "info", **data: object) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=dict(data))

    def _on_loop(self) -> bool:
        """Sommes-nous sur le thread de la boucle qui possède ce hub ?"""

        return self._loop_thread_id is not None and threading.get_ident() == self._loop_thread_id

    # -- cycle de vie -----------------------------------------------------

    @property
    def open_input_streams(self) -> int:
        """0 ou 1. Le compte physique de **ce** hub, pas celui du processus —
        pour le processus entier, voir `input_ownership.open_input_stream_count`."""

        return 1 if self._stream is not None else 0

    @property
    def running(self) -> bool:
        return self.state is CaptureHubState.OPEN

    async def open(self) -> None:
        """Prendre le micro. Lève, nommément, si la propriété ne peut pas être établie."""

        async with self._open_lock:
            if self._stream is not None and self.state is CaptureHubState.OPEN:
                return
            if self._stream is not None:
                # Un flux mort (périphérique perdu) est rendu avant d'en
                # reprendre un : rouvrir par-dessus en laisserait deux inscrits.
                await self._release_stream_locked()
            self._loop = asyncio.get_running_loop()
            self._loop_thread_id = threading.get_ident()
            try:
                # Ouvrir PortAudio coûte des centaines de millisecondes : hors
                # de la boucle, comme `SoundDeviceRealtimeAudio._open`.
                stream = await asyncio.to_thread(
                    self._stream_factory,
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="int16",
                    device=self.device,
                    blocksize=self.block_frames,
                    callback=self._callback,
                )
            except Exception as exc:
                busy = _is_device_busy(exc)
                code = "capture_device_busy" if busy else "capture_device_unavailable"
                detail = f"{type(exc).__name__}: {exc}"
                self._trace(
                    "audio.capture_hub.open_failed",
                    f"Micro indisponible pour la capture partagée : {detail}",
                    level="error", code=code, device=str(self.device), busy=busy,
                    sample_rate=self.sample_rate,
                )
                raise AudioCaptureHubError(
                    code,
                    "Le micro est déjà pris par un autre flux : " + detail
                    if busy else
                    "Impossible d'ouvrir le micro pour la capture partagée : " + detail,
                ) from exc
            self._stream = stream
            register_input_stream(OWNER_CAPTURE_HUB, stream, label=str(self.device))
            self.state = CaptureHubState.OPEN
            self._last_block_at = self.clock()
            self._reported_drops.clear()
            self._supervisor = asyncio.create_task(self._supervise(), name="jarvis-capture-hub-supervisor")
            # Le chemin normal se journalise aussi : sans cette ligne,
            # « rien dans le journal » voudrait dire à la fois « tout va bien »
            # et « mort », et personne ne pourrait les distinguer.
            self._trace(
                "audio.capture_hub.opened",
                "Capture partagée ouverte : un seul propriétaire du micro",
                sample_rate=self.sample_rate, block_frames=self.block_frames,
                device=str(self.device), preroll_ms=self.preroll.preroll_ms,
                process_input_streams=open_input_stream_count(),
            )

    async def _release_stream_locked(self) -> None:
        """Rendre le flux physique. Appelé sous `_open_lock`."""

        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            # `stop()` attend la fin du callback en cours ; libérer le flux
            # avant cela est la violation d'accès du 8 septembre (voir
            # `realtime_audio.SoundDeviceRealtimeAudio`).
            await asyncio.to_thread(_shutdown_input_stream, stream)
        except Exception as exc:
            self._trace(
                "audio.capture_hub.close_failed",
                f"Fermeture du micro partagé en échec : {type(exc).__name__}: {exc}",
                level="error", code="capture_close_failed",
            )
        finally:
            release_input_stream(stream)

    async def close(self) -> None:
        """Rendre le micro. Idempotent, et le hub redevient ouvrable."""

        async with self._open_lock:
            supervisor, self._supervisor = self._supervisor, None
            if supervisor is not None:
                supervisor.cancel()
                await asyncio.gather(supervisor, return_exceptions=True)
            for subscription in tuple(self._subscriptions):
                subscription.closed = True
                subscription.started = False
                subscription._wake()
            self._subscriptions.clear()
            self._drain_notices()
            await self._release_stream_locked()
            self.preroll.clear()
            self.state = CaptureHubState.CLOSED
            self._trace(
                "audio.capture_hub.closed", "Capture partagée fermée : micro rendu",
                blocks_captured=self.blocks_captured,
                process_input_streams=open_input_stream_count(),
            )

    # -- abonnements ------------------------------------------------------

    def subscribe(
        self,
        name: str,
        *,
        sample_rate: int | None = None,
        max_blocks: int = DEFAULT_SUBSCRIBER_BLOCKS,
        sink: Callable[[bytes], None] | None = None,
        start_paused: bool = False,
    ) -> CaptureSubscription:
        """Attacher un abonné. Possible avant comme après `open()`.

        **Fréquence.** Laissée à `None`, l'abonné reçoit le PCM du hub tel quel.
        Une autre valeur fait poser un rééchantillonneur, appliqué en vidant la
        file, sur la boucle. Ce rééchantillonnage est une **interpolation
        linéaire sans filtre anti-repliement** : à la descente (24 vers 16 kHz)
        le contenu entre 8 et 12 kHz se replie. C'est sans conséquence pour un
        détecteur de mot d'éveil, entraîné sur des micros qui bornent déjà cette
        bande ; **ce n'est pas acceptable pour de la transcription**. Un abonné
        qui transcrit — la lane ambiante de la Slice 06 — doit demander la
        fréquence du hub (`sample_rate=None`) et convertir lui-même s'il le
        doit, avec le filtre qui convient.

        Un abonné **en ligne** (`sink`) ne peut pas demander une autre
        fréquence : convertir dans le thread PortAudio est exactement le travail
        lourd que ce thread n'a pas le droit de faire. Le refus est explicite
        plutôt que silencieusement ignoré. Il n'est pas non plus isolé des
        autres abonnés — voir l'en-tête du module.
        """

        if self.state is CaptureHubState.CLOSED:
            raise AudioCaptureHubError(
                "capture_hub_closed",
                "La capture partagée est fermée : rouvrez-la avant d'abonner quoi que ce soit.",
            )
        rate = self.sample_rate if sample_rate is None else int(sample_rate)
        if rate <= 0:
            raise AudioCaptureHubError(
                "capture_subscription_rate_invalid",
                f"Fréquence d'abonné invalide pour « {name} » : {sample_rate}.",
            )
        if sink is not None and rate != self.sample_rate:
            raise AudioCaptureHubError(
                "capture_subscription_rate_mismatch",
                f"L'abonné en ligne « {name} » demande {rate} Hz alors que la capture est à "
                f"{self.sample_rate} Hz : un rééchantillonnage ne peut pas entrer dans le thread audio.",
            )
        blocks = max(1, min(int(max_blocks), MAX_SUBSCRIBER_BLOCKS))
        subscription = CaptureSubscription(
            self, name=str(name), sample_rate=rate, max_blocks=blocks, sink=sink,
            start_paused=start_paused,
        )
        self._subscriptions.append(subscription)
        self._trace(
            "audio.capture_hub.subscribed", f"Abonné à la capture partagée : {name}",
            name=subscription.name, inline=subscription.inline,
            sample_rate=subscription.sample_rate, max_blocks=subscription.max_blocks,
            started=subscription.started, policy=BACKPRESSURE_POLICY,
        )
        return subscription

    def attach_input(
        self,
        callback: Callable[..., None],
        *,
        name: str = "realtime_audio",
    ) -> CaptureSubscription:
        """Brancher un callback de **forme PortAudio** sur la capture partagée.

        C'est l'`input_source` de `SoundDeviceRealtimeAudio` : il reçoit ici la
        poignée qu'il aurait reçue de `sd.RawInputStream`, et n'ouvre donc plus
        aucun périphérique. Le callback est appelé dans le thread de capture,
        avec la même signature `(indata, frames, time_info, status)` — ce qui
        conserve mot pour mot le contrat de `CaptureProcessor` : annulation
        d'écho et garde d'écho dans le thread audio.

        L'abonnement est créé **en pause**, comme un `RawInputStream` qui ne
        livre rien avant son `start()`. Sans cela, des blocs arriveraient entre
        la création de l'abonnement et l'ouverture de la sortie — une fenêtre
        que le chemin d'origine n'a pas, sur un raccord dont tout l'argument est
        qu'il est identique au chemin d'origine.
        """

        frame_bytes = _BYTES_PER_FRAME

        def sink(block: bytes) -> None:
            callback(block, len(block) // frame_bytes, None, None)

        return self.subscribe(name, sink=sink, start_paused=True)

    def _release_subscription(self, subscription: CaptureSubscription) -> None:
        """Détacher, depuis n'importe quel thread."""

        if self._on_loop() or self._loop is None:
            subscription._wake()
            self._detach(subscription)
            return
        try:
            self._loop.call_soon_threadsafe(self._detach_on_loop, subscription)
        except RuntimeError:
            # La boucle est fermée : plus personne n'attend ce réveil, et la
            # liste d'abonnés disparaît avec elle.
            self._detach(subscription)

    def _detach_on_loop(self, subscription: CaptureSubscription) -> None:
        subscription._wake()
        self._detach(subscription)

    def _detach(self, subscription: CaptureSubscription) -> None:
        try:
            self._subscriptions.remove(subscription)
        except ValueError:
            # Déjà détaché : fermer deux fois est normal et silencieux.
            return
        self._trace(
            "audio.capture_hub.unsubscribed", f"Abonné détaché : {subscription.name}",
            name=subscription.name, delivered=subscription.delivered,
            dropped=subscription.dropped, reason=subscription.detached_reason,
        )

    @property
    def subscriptions(self) -> tuple[CaptureSubscription, ...]:
        return tuple(self._subscriptions)

    # -- thread de capture ------------------------------------------------

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        """Callback PortAudio. **Thread non-asyncio** : rien de bloquant ici,
        aucune primitive asyncio, aucune E/S, aucune exception qui remonte."""

        del frames, time_info, status
        try:
            block = bytes(indata)
        except Exception:  # pragma: no cover - indata est toujours un buffer
            return
        self._on_block(block)

    def _on_block(self, block: bytes) -> None:
        """Le point de fan-out. Séparé du callback pour être testable sans PortAudio."""

        if self._stream is None or not block:
            return
        self.blocks_captured += 1
        self.bytes_captured += len(block)
        self._last_block_at = self.clock()
        self.preroll.append(block)
        woken = False
        for subscription in tuple(self._subscriptions):
            if subscription.closed or not subscription.started:
                continue
            if subscription.inline:
                self._deliver_inline(subscription, block)
                continue
            subscription._offer(block)
            woken = True
        loop = self._loop
        if woken and loop is not None:
            try:
                loop.call_soon_threadsafe(self._wake_subscribers)
            except RuntimeError:
                # La boucle se ferme : les derniers blocs n'ont plus de
                # destinataire, et lever ici ferait tomber le flux PortAudio.
                pass

    def _deliver_inline(self, subscription: CaptureSubscription, block: bytes) -> None:
        """Appeler un abonné en ligne, dans le thread de capture.

        **Pourquoi ce n'est pas le verrou permanent de `CaptureProcessor.observer`.**
        Là-bas, l'observateur est *une* vérification facultative du locuteur :
        la détacher définitivement au premier accroc dégrade une fonction
        annexe et ne coûte rien au micro. Ici, le seul abonné en ligne qui
        existe est `attach_input` — **le chemin interactif**, c'est-à-dire le
        micro du tour en cours. Le détacher pour de bon au premier accroc
        rendrait JARVIS sourd pour le reste de la session, sans recours et sans
        que personne s'en aperçoive : la session resterait « active », le
        fournisseur ne recevrait plus rien, et l'utilisateur parlerait dans le
        vide. On tolère donc `MAX_CONSECUTIVE_SINK_FAILURES` échecs rapprochés
        (fenêtre `SINK_FAILURE_WINDOW_S`), chacun dit, un succès **ou** une
        accalmie remettant le compteur à zéro ; au-delà seulement, l'abonné est
        détaché — bruyamment, et la raison reste lisible dans `detached_reason`.
        """

        sink = subscription.sink
        if sink is None:  # pragma: no cover - inline implique un sink
            return
        try:
            sink(block)
        except Exception as exc:
            now = self.clock()
            previous = subscription._last_failure_at
            if previous is None or now - previous > SINK_FAILURE_WINDOW_S:
                # Accroc isolé : la rafale précédente est oubliée plutôt que
                # cumulée, sinon trois accrocs espacés d'une minute finiraient
                # par détacher l'abonné.
                subscription.consecutive_failures = 0
            subscription._last_failure_at = now
            subscription.failures += 1
            subscription.consecutive_failures += 1
            exhausted = subscription.consecutive_failures >= MAX_CONSECUTIVE_SINK_FAILURES
            self._notice(
                "audio.capture_hub.sink_failed",
                f"Abonné « {subscription.name} » en échec : {type(exc).__name__}: {exc}",
                "error",
                {"code": "capture_sink_failed", "name": subscription.name,
                 "failures": subscription.failures, "detaching": exhausted},
            )
            if exhausted:
                subscription.detached_reason = "capture_sink_failed"
                subscription.closed = True
        else:
            subscription.consecutive_failures = 0
            subscription._last_failure_at = None

    def _notice(self, kind: str, message: str, level: str, data: dict[str, object]) -> None:
        """Déposer un avis produit dans le thread de capture. La boucle le journalise."""

        self._notices.append((kind, message, level, data))

    def _wake_subscribers(self) -> None:
        for subscription in tuple(self._subscriptions):
            if not subscription.inline and subscription.pending:
                subscription._wake()

    # -- surveillance -----------------------------------------------------

    def _drain_notices(self) -> int:
        drained = 0
        while self._notices:
            kind, message, level, data = self._notices.popleft()
            self._trace(kind, message, level=level, **data)
            drained += 1
        # Un abonné détaché dans le thread de capture est retiré ici, sur la
        # boucle : la liste d'abonnés n'est jamais mutée depuis PortAudio.
        for subscription in tuple(self._subscriptions):
            if subscription.closed:
                self._detach(subscription)
        return drained

    def report_backpressure(self) -> int:
        """Dire les pertes de contre-pression qui ont bougé depuis le dernier tour.

        Comptées **et dites** : un abonné qui perd des blocs en silence est
        indiscernable d'un abonné servi. Une ligne par abonné et par tour, et
        seulement quand le compte a changé, pour qu'une salle bruyante
        n'inonde pas le journal.
        """

        said = 0
        for subscription in tuple(self._subscriptions):
            previous = self._reported_drops.get(subscription.name, 0)
            if subscription.dropped <= previous:
                continue
            self._reported_drops[subscription.name] = subscription.dropped
            said += 1
            self._trace(
                "audio.capture_hub.backpressure",
                f"Contre-pression sur « {subscription.name} » : "
                f"{subscription.dropped - previous} blocs écartés (le plus ancien d'abord)",
                level="warning", code="capture_backpressure_dropped",
                name=subscription.name, dropped=subscription.dropped,
                since_last=subscription.dropped - previous,
                max_blocks=subscription.max_blocks, policy=BACKPRESSURE_POLICY,
            )
        return said

    async def _supervise(self) -> None:
        """Journaliser ce que le thread de capture a constaté, et guetter la perte."""

        while True:
            await asyncio.sleep(SUPERVISION_PERIOD_S)
            self._drain_notices()
            self.report_backpressure()
            if not self.check_liveness():
                await self.reap_lost_device()
                return

    def check_liveness(self, now: float | None = None) -> bool:
        """Le micro répond-il encore ? Dit la perte **une fois**, fort.

        Exposé publiquement plutôt que caché dans la boucle du surveillant :
        un test doit pouvoir avancer l'horloge et constater la perte sans
        attendre en temps réel. La bascule d'état **est** ce qui rend la perte
        dite une seule fois — l'entrée de cette méthode refuse tout état autre
        qu'OPEN.
        """

        if self._stream is None or self.state is not CaptureHubState.OPEN:
            return False
        observed = self._last_block_at
        moment = self.clock() if now is None else float(now)
        if observed is None or moment - observed <= self.silence_timeout_s:
            return True
        self.state = CaptureHubState.LOST
        silent_s = round(moment - observed, 3)
        self._trace(
            "audio.capture_hub.device_lost",
            f"Le micro partagé ne rend plus rien depuis {silent_s} s : capture perdue",
            level="error", code="capture_device_lost", silent_s=silent_s,
            blocks_captured=self.blocks_captured,
        )
        if self.on_device_lost is not None:
            try:
                self.on_device_lost("capture_device_lost")
            except Exception as exc:
                # Un abonné qui explose en apprenant la perte ne doit pas
                # empêcher les autres de l'apprendre.
                self._trace(
                    "audio.capture_hub.device_lost_listener_failed",
                    f"Prévenir de la perte du micro a échoué : {type(exc).__name__}: {exc}",
                    level="error", code="capture_device_lost_listener_failed",
                )
        return False

    async def reap_lost_device(self) -> bool:
        """Rendre le périphérique perdu, au lieu de le tenir mort.

        Sans cela la perte serait un cul-de-sac : le flux resterait inscrit au
        registre des propriétaires, `open()` refuserait de rouvrir puisqu'il en
        tient déjà un, et toute activation ultérieure de PRESENTATION serait
        refusée pour cause de « second propriétaire » — son propre cadavre.
        """

        if self.state is not CaptureHubState.LOST or self._stream is None:
            return False
        async with self._open_lock:
            if self._stream is None:
                return False
            await self._release_stream_locked()
        self._trace(
            "audio.capture_hub.device_released",
            "Micro perdu rendu : la capture peut être reprise",
            level="warning", code="capture_device_released",
            process_input_streams=open_input_stream_count(),
        )
        return True

    def stats(self) -> dict[str, object]:
        """État lisible du hub. Aucun octet audio, seulement des compteurs."""

        return {
            "state": self.state.value,
            "sample_rate": self.sample_rate,
            "block_frames": self.block_frames,
            "open_input_streams": self.open_input_streams,
            "process_input_streams": open_input_stream_count(),
            "blocks_captured": self.blocks_captured,
            "bytes_captured": self.bytes_captured,
            "preroll_bytes_held": self.preroll.bytes_held,
            "preroll_capacity_bytes": self.preroll.capacity_bytes,
            "subscriptions": [subscription.stats() for subscription in self._subscriptions],
        }


def _shutdown_input_stream(stream: object) -> None:
    """Arrêter puis fermer, dans cet ordre, hors de la boucle."""

    stop = getattr(stream, "stop", None)
    if stop is not None:
        stop()
    close = getattr(stream, "close", None)
    if close is not None:
        close()


def _is_device_busy(exc: BaseException) -> bool:
    """`PortAudioError(msg, paDeviceUnavailable)`, sans importer sounddevice.

    Même technique que `realtime_audio._is_stream_already_stopped` : on lit le
    code que PortAudio range en second argument, plutôt que d'inspecter un
    message traduit.
    """

    args = getattr(exc, "args", ())
    if type(exc).__name__ == "PortAudioError" and len(args) > 1 and args[1] == _PA_DEVICE_UNAVAILABLE:
        return True
    return False
