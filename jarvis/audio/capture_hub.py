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

Contre-pression
---------------

Chaque file est bornée et **jamais bloquante**. Un abonné lent perd des blocs ;
il ne ralentit ni le thread de capture ni les autres abonnés. La politique par
défaut est `DROP_OLDEST`, la même que `SoundDeviceRealtimeAudio._put_input` :
quand la file déborde, ce qui vaut encore quelque chose est le **présent**, pas
un arriéré. Chaque perte est comptée et dite ; rien ne disparaît sans un mot.

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

_BYTES_PER_FRAME = 2  # int16 mono

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

#: Échecs consécutifs tolérés d'un abonné **en ligne** avant détachement. Voir
#: `_deliver_inline` pour l'argument : ce n'est délibérément pas le verrou
#: permanent au premier échec de `CaptureProcessor.observer`.
MAX_CONSECUTIVE_SINK_FAILURES = 3

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


class BackpressurePolicy(str, Enum):
    """Que faire quand la file bornée d'un abonné est pleine."""

    #: Écarter le plus ancien. Défaut : un consommateur qui a pris du retard
    #: veut entendre le présent, pas rattraper le passé.
    DROP_OLDEST = "drop_oldest"
    #: Écarter le nouveau et garder l'arriéré intact. Pour un abonné dont la
    #: continuité compte davantage que la fraîcheur.
    DROP_NEWEST = "drop_newest"


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
        self._blocks.clear()
        self.bytes_held = 0


class CaptureSubscription:
    """Un abonné au PCM partagé. Borné, détachable, sans effet sur les autres.

    Ressemble volontairement à un flux `sounddevice` (`stop()` / `close()` avec
    `ignore_errors`) : c'est ce qui permet à `SoundDeviceRealtimeAudio` de le
    traiter exactement comme le `RawInputStream` qu'il n'ouvre plus, sans une
    seule branche supplémentaire dans ses chemins de fermeture.
    """

    def __init__(
        self,
        hub: "AudioCaptureHub",
        *,
        name: str,
        sample_rate: int,
        max_blocks: int,
        policy: BackpressurePolicy,
        sink: Callable[[bytes], None] | None,
    ) -> None:
        self._hub = hub
        self.name = name
        self.sample_rate = sample_rate
        self.policy = policy
        self.max_blocks = max_blocks
        self.sink = sink
        self.inline = sink is not None
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
        self.detached_reason: str | None = None
        self.closed = False

    # -- côté thread de capture -------------------------------------------

    def _offer(self, block: bytes) -> None:
        """Déposer un bloc. Appelé dans le thread PortAudio : ne bloque jamais,
        ne lève jamais, n'alloue rien d'illimité."""

        if len(self._blocks) >= self.max_blocks:
            if self.policy is BackpressurePolicy.DROP_NEWEST:
                self.dropped += 1
                return
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

    def start(self) -> None:
        """Sans objet : le hub est déjà démarré. Présent pour que l'abonnement
        se comporte comme le `RawInputStream` qu'il remplace."""

    def stop(self, *, ignore_errors: bool = True) -> None:
        """Arrêter la livraison. Ne ferme **pas** le flux physique du hub."""

        del ignore_errors
        self._blocks.clear()

    def close(self, *, ignore_errors: bool = True) -> None:
        """Se détacher du hub. Idempotent. Ne ferme **pas** le flux physique."""

        del ignore_errors
        if self.closed:
            return
        self.closed = True
        self._blocks.clear()
        self._event.set()  # Libérer un `blocks()` en attente.
        self._hub._detach(self)

    def stats(self) -> dict[str, object]:
        return {
            "name": self.name,
            "inline": self.inline,
            "sample_rate": self.sample_rate,
            "policy": self.policy.value,
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

    Cycle de vie : `open()` puis `close()`, tous deux idempotents et rejouables
    — un hub fermé peut être rouvert, ce qui est ce dont une bascule
    PRESENTATION → SIMPLE → PRESENTATION a besoin.

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
        journal: object | None = None,
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
        self._supervisor: asyncio.Task[None] | None = None
        self._open_lock = asyncio.Lock()
        #: Avis produits dans le thread de capture, journalisés depuis la
        #: boucle. Le thread PortAudio n'écrit pas de fichier — même règle que
        #: `CaptureProcessor.take_alignments`.
        self._notices: deque[tuple[str, str, str, dict[str, object]]] = deque(maxlen=MAX_PENDING_NOTICES)
        self.blocks_captured = 0
        self.bytes_captured = 0
        self._last_block_at: float | None = None

    # -- traces -----------------------------------------------------------

    def _trace(self, kind: str, message: str, *, level: str = "info", **data: object) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=dict(data))

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
            if self._stream is not None:
                return
            self._loop = asyncio.get_running_loop()
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

    async def close(self) -> None:
        """Rendre le micro. Idempotent, et le hub redevient ouvrable."""

        async with self._open_lock:
            supervisor, self._supervisor = self._supervisor, None
            if supervisor is not None:
                supervisor.cancel()
                await asyncio.gather(supervisor, return_exceptions=True)
            for subscription in tuple(self._subscriptions):
                subscription.closed = True
                subscription._event.set()
            self._subscriptions.clear()
            stream, self._stream = self._stream, None
            self._drain_notices()
            if stream is not None:
                try:
                    # `stop()` attend la fin du callback en cours ; libérer le
                    # flux avant cela est la violation d'accès du 8 septembre
                    # (voir `realtime_audio.SoundDeviceRealtimeAudio`).
                    await asyncio.to_thread(_shutdown_input_stream, stream)
                except Exception as exc:
                    self._trace(
                        "audio.capture_hub.close_failed",
                        f"Fermeture du micro partagé en échec : {type(exc).__name__}: {exc}",
                        level="error", code="capture_close_failed",
                    )
                finally:
                    release_input_stream(stream)
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
        policy: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST,
        sink: Callable[[bytes], None] | None = None,
    ) -> CaptureSubscription:
        """Attacher un abonné. Possible avant comme après `open()`.

        Un abonné **en ligne** (`sink`) ne peut pas demander une autre
        fréquence : convertir dans le thread PortAudio est exactement le travail
        lourd que ce thread n'a pas le droit de faire. Le refus est explicite
        plutôt que silencieusement ignoré.
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
            self, name=str(name), sample_rate=rate, max_blocks=blocks, policy=policy, sink=sink,
        )
        self._subscriptions.append(subscription)
        self._trace(
            "audio.capture_hub.subscribed", f"Abonné à la capture partagée : {name}",
            **{k: v for k, v in subscription.stats().items() if k in ("name", "inline", "sample_rate", "policy", "max_blocks")},
        )
        return subscription

    def attach_input(
        self,
        callback: Callable[..., None],
        *,
        name: str = "realtime_audio",
        ignore_errors: bool = False,
    ) -> CaptureSubscription:
        """Brancher un callback de **forme PortAudio** sur la capture partagée.

        C'est l'`input_source` de `SoundDeviceRealtimeAudio` : il reçoit ici la
        poignée qu'il aurait reçue de `sd.RawInputStream`, et n'ouvre donc plus
        aucun périphérique. Le callback est appelé dans le thread de capture,
        avec la même signature `(indata, frames, time_info, status)` — ce qui
        conserve mot pour mot le contrat de `CaptureProcessor` : annulation
        d'écho et garde d'écho dans le thread audio.
        """

        del ignore_errors
        frame_bytes = _BYTES_PER_FRAME

        def sink(block: bytes) -> None:
            callback(block, len(block) // frame_bytes, None, None)

        return self.subscribe(name, sink=sink)

    def _detach(self, subscription: CaptureSubscription) -> None:
        try:
            self._subscriptions.remove(subscription)
        except ValueError:
            # Déjà détaché : fermer deux fois est normal et silencieux.
            return
        self._trace(
            "audio.capture_hub.unsubscribed", f"Abonné détaché : {subscription.name}",
            **{"name": subscription.name, "delivered": subscription.delivered,
               "dropped": subscription.dropped, "reason": subscription.detached_reason},
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
            if subscription.closed:
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
        annexe et ne coûte rien au micro. Ici, un abonné est une **lane** —
        celle qui porte le chemin interactif ou la détection d'adresse — et
        `docs/03-implementation-strategy.md` exige qu'une panne du détecteur
        « se voie clairement et laisse la touche manuelle utilisable » : la
        détacher pour de bon au premier accroc tuerait le mot d'éveil pour le
        reste de la séance, sans recours et sans que personne s'en aperçoive.
        On tolère donc `MAX_CONSECUTIVE_SINK_FAILURES` échecs **consécutifs**,
        chacun dit, un succès remettant le compteur à zéro ; au-delà seulement,
        l'abonné est détaché — bruyamment, et la raison reste lisible dans
        `detached_reason`.
        """

        sink = subscription.sink
        if sink is None:  # pragma: no cover - inline implique un sink
            return
        try:
            sink(block)
        except Exception as exc:
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

    async def _supervise(self) -> None:
        """Journaliser ce que le thread de capture a constaté, et guetter la perte."""

        try:
            while True:
                await asyncio.sleep(SUPERVISION_PERIOD_S)
                self._drain_notices()
                self.check_liveness()
        except asyncio.CancelledError:
            raise

    def check_liveness(self, now: float | None = None) -> bool:
        """Le micro répond-il encore ? Dit la perte **une fois**, fort.

        Exposé publiquement plutôt que caché dans la boucle du surveillant :
        un test doit pouvoir avancer l'horloge et constater la perte sans
        attendre en temps réel.
        """

        if self._stream is None or self.state is not CaptureHubState.OPEN:
            return False
        observed = self._last_block_at
        moment = self.clock() if now is None else float(now)
        if observed is None or moment - observed <= self.silence_timeout_s:
            return True
        # La bascule d'etat **est** ce qui rend la perte dite une seule fois :
        # l'entree de cette methode refuse tout etat autre qu'OPEN. Un second
        # drapeau ne protegerait rien et serait du poids mort (lecon Slice 03).
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
