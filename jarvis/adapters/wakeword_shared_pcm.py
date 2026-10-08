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
et journalisée à `error`, la détection s'arrête en le **disant**, et rien
d'autre ne tombe : le hub continue de capter pour les autres lanes, et la
touche manuelle — qui ne passe pas par ici du tout — continue d'adresser
JARVIS.

« En le disant » a trois sens, et il a fallu les trois :

1. `engine_failed` / `failure_code` sont lisibles de l'extérieur ;
2. l'abonnement PCM **est réellement rendu**, dans un `finally` : sinon le hub
   continuerait d'alimenter une lane morte, ses pertes gonfleraient, et
   `hub.stats()` la présenterait comme vivante ;
3. `detections()` **se termine par une exception nommée** au lieu de rester
   bloqué sur une file qui ne se remplira plus. Sans cela, la lane d'adresse
   explicite n'apprendrait jamais la panne et `live_sources` continuerait de
   déclarer le mot d'éveil vivant après sa mort — le contraire exact de ce que
   cette section promet.

Rien n'est persisté : les trames vivent dans un tampon d'assemblage borné.

Score, seuil, fournisseur : sans toucher au port
------------------------------------------------

`WakeWordBackend.detections()` ne transporte que des chaînes, et ce contrat ne
change pas. La confiance de la détection reste donc **sur le moteur**
(`last_score`, `threshold`, `provider` pour `OpenWakeWordEngine`) et le backend,
qui détient le moteur, la lit au moment où il le voit détecter, par duck-typing
(`getattr`, absent pour Porcupine) : il écrit **une** ligne de journal
`wake.shared_pcm.detected` portant `keyword`, `provider` et, si le moteur les
a, `score` et `threshold`. Journal seulement : jamais la ligne de temps, dont
`ATTRIBUTE_KEYS` reste fermé.

La mesure est **appariée** à sa détection : la file porte des paires
`(mot, mesure)` et `last_detection` est écrit par `detections()` au moment où
il rend le mot, jamais au moment où le moteur détecte (deux détections
rapprochées ne s'échangent donc pas leurs scores ; une détection perdue par
file pleine n'enfile rien et ne décale rien). `voice.wake` (émis par Voice)
porte `provider`, `score` et `threshold` de cette même détection, lus par
`CompositeWakeWordBackend` ; les deux lignes portent le même score.
"""

from __future__ import annotations

import asyncio
import math
import struct
from collections.abc import AsyncIterator, Callable

from jarvis.audio.capture_hub import AudioCaptureHub, CaptureSubscription
from jarvis.ports.v2 import DiagnosticSink

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

#: Jeton posé dans la file quand le détecteur meurt : c'est lui qui débloque
#: `detections()` pour qu'elle lève au lieu d'attendre indéfiniment.
_FAILED = object()


class WakeWordDetectorFailed(RuntimeError):
    """Le détecteur de mot d'éveil est hors service ; la lane doit l'apprendre."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
        journal: DiagnosticSink | None = None,
        name: str = "wake_word",
        provider: str | None = None,
    ) -> None:
        self.hub = hub
        self.engine_factory = engine_factory
        self.keyword = keyword
        #: Nom du fournisseur pour les traces ; le moteur, s'il en porte un
        #: (`engine.provider`), l'emporte.
        self.provider = provider
        self.journal = journal
        self.name = name
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=DETECTION_QUEUE_SIZE)
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
        #: Fournisseur, score et seuil de la dernière détection (scalaires finis
        #: seulement), pour la trace `voice.wake` de Voice ; `None` avant la première.
        self.last_detection: dict[str, object] | None = None
        self.frames_processed = 0
        #: Détections écartées parce que la file était pleine. Un mot d'éveil
        #: perdu est un fait, jamais un silence.
        self.dropped = 0
        #: Détections jetées par une suspension. Comptées et dites, elles aussi :
        #: « la file a été vidée » ne doit pas être indiscernable de
        #: « personne n'avait rien dit ».
        self.discarded = 0
        #: Blocs PCM écartés par la file bornée de l'abonné (le détecteur est en
        #: retard sur la capture). Conservé après la libération de l'abonnement.
        self._pcm_dropped_released = 0

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
        if self._closed:
            # Un backend fermé ne redémarre pas : le dire, parce qu'un retour
            # silencieux ici a produit une séance PRESENTATION sourde qui
            # s'annonçait vivante (voir `PresentationAudioSession.start`).
            self._trace(
                "wake.shared_pcm.closed_restart_refused",
                "Détection du mot d'éveil déjà fermée : elle ne redémarre pas.",
                level="error", code="wake_backend_closed", keyword=self.keyword,
            )
            return
        if self._task is not None:
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
        finally:
            if self.engine_failed:
                # Rendre l'abonnement **et** le moteur : un détecteur mort qui
                # reste abonné continuerait d'être alimenté et de perdre des
                # blocs, et `hub.stats()` le présenterait comme vivant.
                self._release_subscription()
                self._release_engine()

    def _release_subscription(self) -> None:
        """Rendre l'abonnement PCM. Idempotent ; ne ferme jamais le micro."""

        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            self._pcm_dropped_released += int(getattr(subscription, "dropped", 0))
            subscription.close()

    def _detected(self) -> None:
        self.detections_count += 1
        measures = self._trace_detection()
        if self._queue.full():
            self.dropped += 1
            self._trace(
                "wake.shared_pcm.dropped",
                "Mot d'éveil écarté : la file de déclencheurs est pleine",
                level="warning", code="wake_detection_dropped", dropped=self.dropped,
            )
            return
        # La mesure voyage AVEC sa détection : `detections()` la publie au moment
        # où elle rend ce mot, pas au moment où le moteur l'a mesurée.
        self._queue.put_nowait((self.keyword, measures))

    def _trace_detection(self) -> dict[str, object]:
        """Une ligne de journal par détection : fournisseur, score et seuil du moteur.

        Scalaires seulement. Un moteur sans score (Porcupine) n'en porte pas.
        """

        data: dict[str, object] = {"keyword": self.keyword}
        # Une trace ne fait jamais perdre la détection : toute lecture qui lève
        # est omise, et seul un flottant fini part dans le journal (JSON valide).
        def read(attr: str) -> object:
            try:
                return getattr(self._engine, attr, None)
            except Exception:  # noqa: BLE001 - la trace est accessoire
                return None

        provider = read("provider") or self.provider
        if provider:
            data["provider"] = str(provider)
        for key, attr in (("score", "last_score"), ("threshold", "threshold")):
            value = read(attr)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                try:
                    if math.isfinite(value):
                        data[key] = round(float(value), 4)
                except (OverflowError, ValueError):  # pragma: no cover - entier géant
                    pass
        measures = {key: value for key, value in data.items() if key != "keyword"}
        self._trace("wake.shared_pcm.detected", "Mot d'éveil reconnu", **data)
        return measures

    def _fail(self, code: str, exc: BaseException) -> None:
        """Dire la panne, arrêter la détection, ne rien emporter avec elle."""

        self.engine_failed = True
        self.failure_code = code
        # La cause stable du moteur (`cause_code` d'un moteur indisponible, sinon
        # son propre `code`), pour qu'une panne se lise sans fouiller le message.
        cause = getattr(exc, "cause_code", None) or getattr(exc, "code", None)
        extra: dict[str, object] = {}
        if isinstance(cause, str) and cause and cause != code:
            extra["cause_code"] = cause
        if self.provider:
            extra["provider"] = self.provider
        self._trace(
            "wake.shared_pcm.failed",
            f"Détection du mot d'éveil hors service : {type(exc).__name__}: {exc}. "
            "La touche manuelle reste utilisable.",
            level="error", code=code, keyword=self.keyword, **extra,
        )
        # Débloquer `detections()` : sans ce jeton elle attendrait pour toujours
        # une file qui ne se remplira plus, et la lane continuerait de déclarer
        # cette source vivante.
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - full() vient d'être vrai
                pass
        self._queue.put_nowait(_FAILED)

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
        """Rendre les mots d'éveil reconnus, et **lever** si le détecteur meurt.

        Lever plutôt que se terminer en silence est délibéré : c'est le seul
        signal que `ExplicitAddressLane._pump` peut transformer en une entrée de
        `source_failures`, donc le seul qui empêche `live_sources` de déclarer
        vivante une source morte.
        """

        await self.start()
        if self.engine_failed:
            raise WakeWordDetectorFailed(
                self.failure_code or "wake_engine_unavailable",
                "Le détecteur de mot d'éveil n'a pas pu démarrer.",
            )
        while not self._closed:
            item = await self._queue.get()
            if item is _FAILED:
                raise WakeWordDetectorFailed(
                    self.failure_code or "wake_engine_failed",
                    "Le détecteur de mot d'éveil s'est arrêté en cours de séance.",
                )
            keyword, measures = item
            # Appariement : la mesure de CE mot, publiée juste avant de le rendre,
            # sans point d'attente entre les deux.
            self.last_detection = measures
            yield str(keyword)

    async def suspend(self) -> None:
        """Couper la détection. Ne ferme **ni** l'abonnement **ni** le micro.

        Ce que la suspension jette est **compté et dit**.
        `CompositeWakeWordBackend` vide sa file en silence ; ici un mot d'éveil
        reconnu puis effacé est un fait que l'utilisateur a produit, et il ne
        doit pas disparaître sans une ligne.
        """

        self._enabled = False
        discarded = self._drain_queue()
        if discarded:
            self.discarded += discarded
            self._trace(
                "wake.shared_pcm.discarded",
                f"{discarded} mot(s) d'éveil effacé(s) par la suspension",
                level="warning", code="wake_detection_discarded",
                discarded=self.discarded, since_last=discarded,
            )

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

    def _drain_queue(self) -> int:
        """Vider la file. Rend combien de détections réelles ont été jetées."""

        discarded = 0
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - empty() vient d'être vrai
                break
            if item is _FAILED:
                # Le jeton de panne se remet : la panne ne s'efface pas avec la
                # file, et `detections()` doit encore pouvoir lever.
                self._queue.put_nowait(_FAILED)
                break
            discarded += 1
        return discarded

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._enabled = False
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._release_subscription()
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
            "discarded": self.discarded,
            "pcm_blocks_dropped": self._pcm_dropped_released
            + (int(getattr(self._subscription, "dropped", 0)) if self._subscription is not None else 0),
            "provider": self.provider,
            "enabled": self._enabled,
            "closed": self._closed,
            "subscribed": self._subscription is not None,
        }
