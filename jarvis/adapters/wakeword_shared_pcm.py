"""Détection de mot d'éveil nourrie par le PCM **partagé**, pas par un second micro.

`PorcupineWakeWordBackend` ouvre son propre `sd.RawInputStream`. En SIMPLE cela
tient parce qu'il se ferme pendant une session active ; en PRESENTATION rien ne
se ferme, et ce second flux serait le deuxième propriétaire du micro que
`docs/03-implementation-strategy.md` interdit. Ce backend-ci fait exactement le
même travail à partir d'un abonnement au `AudioCaptureHub` : **zéro flux
physique**, le compteur de `jarvis.audio.input_ownership` le prouve.

Le moteur est injecté (`engine_factory`). `pvporcupine` n'est importé que par
`porcupine_engine_factory`, donc la suite de tests n'a jamais besoin de la
bibliothèque, ni d'une clé d'accès, ni du périphérique.

Panne du moteur
---------------

`docs/03-implementation-strategy.md` : « Wake detector failure must surface
clearly and leave manual key usable. » Une exception du moteur est donc comptée
et journalisée à `error`, la détection s'arrête en le **disant** (`engine_failed`,
lisible de l'extérieur), et rien d'autre ne tombe : l'abonnement est rendu, le
hub continue de capter pour les autres lanes, et la touche manuelle — qui ne
passe pas par ici du tout — continue d'adresser JARVIS.

Rien n'est persisté : les trames vivent dans un tampon d'assemblage borné.
"""

from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncIterator, Callable

from jarvis.audio.capture_hub import AudioCaptureHub, BackpressurePolicy, CaptureSubscription

_BYTES_PER_SAMPLE = 2  # int16 mono

#: Profondeur de la file de détections. Même valeur que
#: `CompositeWakeWordBackend` : c'est le motif de fan-in borné déjà en place
#: dans ce dépôt, et deux profondeurs différentes pour la même chose seraient
#: une divergence gratuite.
DETECTION_QUEUE_SIZE = 4

#: Profondeur de l'abonnement PCM. Le détecteur consomme par trames de 512
#: échantillons (32 ms) et ne bloque jamais longtemps ; 16 blocs de 50 ms
#: suffisent largement, et au-delà on servirait au moteur un arriéré qui
#: reconnaîtrait un mot d'éveil déjà vieux d'une seconde.
SUBSCRIBER_BLOCKS = 16

#: Garde-fou du tampon d'assemblage : jamais plus de deux trames en attente
#: d'être complétées. Sans lui, un `frame_length` aberrant ferait grossir un
#: `bytearray` sans borne.
MAX_CARRY_FRAMES = 2


class WakeWordEngine:
    """Ce que le backend attend d'un moteur (forme de `pvporcupine.Porcupine`)."""

    frame_length: int
    sample_rate: int

    def process(self, pcm) -> int:  # noqa: ANN001  # pragma: no cover - protocole
        raise NotImplementedError

    def delete(self) -> None:  # pragma: no cover - protocole
        raise NotImplementedError


def porcupine_engine_factory(*, access_key: str, keyword: str) -> Callable[[], WakeWordEngine]:
    """Fabrique paresseuse : `pvporcupine` n'est importé qu'à la construction."""

    def build() -> WakeWordEngine:
        import pvporcupine  # type: ignore

        return pvporcupine.create(access_key=access_key, keywords=[keyword])

    return build


class SharedPcmWakeWordBackend:
    """`WakeWordBackend` alimenté par le hub. N'ouvre jamais de périphérique."""

    def __init__(
        self,
        *,
        hub: AudioCaptureHub,
        engine_factory: Callable[[], WakeWordEngine],
        keyword: str = "jarvis",
        journal: object | None = None,
        name: str = "wake_word",
    ) -> None:
        self.hub = hub
        self.engine_factory = engine_factory
        self.keyword = keyword
        self.journal = journal
        self.name = name
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=DETECTION_QUEUE_SIZE)
        self._engine: WakeWordEngine | None = None
        self._subscription: CaptureSubscription | None = None
        self._task: asyncio.Task[None] | None = None
        self._carry = bytearray()
        self._closed = False
        self._enabled = True
        #: Observables depuis l'extérieur : une panne de détection doit pouvoir
        #: se constater, pas seulement se lire dans un journal.
        self.engine_failed = False
        self.failure_code: str | None = None
        self.detections_count = 0
        self.frames_processed = 0
        #: Détections écartées parce que la file était pleine. Un mot d'éveil
        #: perdu est un fait, jamais un silence.
        self.dropped = 0

    # -- traces -----------------------------------------------------------

    def _trace(self, kind: str, message: str, *, level: str = "info", **data: object) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=dict(data))

    @property
    def opens_input_stream(self) -> bool:
        """Toujours faux. C'est la raison d'être de cette classe, et un test le compte."""

        return False

    # -- cycle de vie -----------------------------------------------------

    async def start(self) -> None:
        if self._closed or self._task is not None:
            return
        if self.engine_failed:
            # Un moteur déjà tombé ne se relance pas en boucle : il se redit.
            return
        try:
            engine = self.engine_factory()
        except Exception as exc:
            self._fail("wake_engine_unavailable", exc)
            return
        self._engine = engine
        try:
            self._subscription = self.hub.subscribe(
                self.name,
                sample_rate=int(engine.sample_rate),
                max_blocks=SUBSCRIBER_BLOCKS,
                policy=BackpressurePolicy.DROP_OLDEST,
            )
        except Exception as exc:
            self._fail("wake_subscription_refused", exc)
            self._release_engine()
            return
        self._carry.clear()
        self._task = asyncio.create_task(self._consume(), name="jarvis-wake-shared-pcm")
        self._trace(
            "wake.shared_pcm.started",
            "Détection du mot d'éveil branchée sur la capture partagée",
            keyword=self.keyword, engine_sample_rate=int(engine.sample_rate),
            hub_sample_rate=self.hub.sample_rate,
            resampled=int(engine.sample_rate) != self.hub.sample_rate,
        )

    async def _consume(self) -> None:
        subscription, engine = self._subscription, self._engine
        if subscription is None or engine is None:  # pragma: no cover - start les pose
            return
        frame_bytes = max(1, int(engine.frame_length)) * _BYTES_PER_SAMPLE
        unpack = "h" * int(engine.frame_length)
        try:
            async for block in subscription.blocks():
                self._carry.extend(block)
                # Borne du tampon d'assemblage : on ne garde jamais un arriéré.
                limit = frame_bytes * MAX_CARRY_FRAMES
                if len(self._carry) > limit:
                    del self._carry[: len(self._carry) - limit]
                while len(self._carry) >= frame_bytes:
                    frame = bytes(self._carry[:frame_bytes])
                    del self._carry[:frame_bytes]
                    if not self._enabled:
                        continue
                    try:
                        detected = engine.process(struct.unpack(unpack, frame))
                    except Exception as exc:
                        self._fail("wake_engine_failed", exc)
                        return
                    self.frames_processed += 1
                    if detected is not None and detected >= 0:
                        self._detected()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail("wake_consume_failed", exc)

    def _detected(self) -> None:
        self.detections_count += 1
        if self._queue.full():
            self.dropped += 1
            self._trace(
                "wake.shared_pcm.dropped",
                "Mot d'éveil écarté : la file de déclencheurs est pleine",
                level="warning", code="wake_detection_dropped", dropped=self.dropped,
            )
            return
        self._queue.put_nowait(self.keyword)

    def _fail(self, code: str, exc: BaseException) -> None:
        """Dire la panne, arrêter la détection, ne rien emporter avec elle."""

        self.engine_failed = True
        self.failure_code = code
        self._trace(
            "wake.shared_pcm.failed",
            f"Détection du mot d'éveil hors service : {type(exc).__name__}: {exc}. "
            "La touche manuelle reste utilisable.",
            level="error", code=code, keyword=self.keyword,
        )

    def _release_engine(self) -> None:
        engine, self._engine = self._engine, None
        if engine is None:
            return
        try:
            engine.delete()
        except Exception as exc:
            # Libérer le moteur est au mieux : échouer ici ne doit pas empêcher
            # la fermeture, mais ne doit pas non plus être muet.
            self._trace(
                "wake.shared_pcm.engine_release_failed",
                f"Libération du moteur de mot d'éveil en échec : {type(exc).__name__}: {exc}",
                level="warning", code="wake_engine_release_failed",
            )

    # -- contrat WakeWordBackend ------------------------------------------

    async def detections(self) -> AsyncIterator[str]:
        await self.start()
        while not self._closed:
            yield await self._queue.get()

    async def suspend(self) -> None:
        """Couper la détection. Ne ferme **ni** l'abonnement **ni** le micro."""

        self._enabled = False
        self._drain_queue()

    async def suspend_for_active_session(self) -> None:
        """Même sens qu'ailleurs : pendant une session active, le mot d'éveil se tait.

        Parité stricte avec `PorcupineWakeWordBackend`, moins la fermeture du
        périphérique — qui n'a plus lieu d'être puisqu'il n'y en a pas. La
        touche manuelle, elle, garde son comportement propre
        (`KeyboardWakeWordBackend.suspend_for_active_session` la laisse armée
        pour qu'un second appui soumette le tour) : ce backend ne la touche pas.
        """

        await self.suspend()

    async def resume(self) -> None:
        if self._closed:
            return
        self._enabled = True
        await self.start()

    def _drain_queue(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - empty() vient d'être vrai
                break

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._enabled = False
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            subscription.close()
        self._release_engine()
        self._carry.clear()
        self._trace(
            "wake.shared_pcm.closed", "Détection du mot d'éveil arrêtée",
            detections=self.detections_count, frames=self.frames_processed, dropped=self.dropped,
        )

    def stats(self) -> dict[str, object]:
        return {
            "keyword": self.keyword,
            "opens_input_stream": self.opens_input_stream,
            "engine_failed": self.engine_failed,
            "failure_code": self.failure_code,
            "detections": self.detections_count,
            "frames_processed": self.frames_processed,
            "dropped": self.dropped,
            "enabled": self._enabled,
        }
