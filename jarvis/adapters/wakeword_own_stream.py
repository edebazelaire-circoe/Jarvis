"""Détecteur de mot d'éveil SIMPLE à flux propre, porté par un moteur **injecté**.

En SIMPLE (`BACKGROUND`, aucun hub au repos) il n'existe pas de capture
partagée : écouter « Hey Jarvis » demande donc que le détecteur ouvre son
propre `sd.RawInputStream`, comme `PorcupineWakeWordBackend`. Ce module fait ce
travail pour un moteur quelconque (`engine_factory`), en particulier
`OpenWakeWordEngine`, avec une différence qui est toute la raison d'être de ce
fichier : **l'inférence ne tourne jamais dans le rappel PortAudio**
(décision D7). Porcupine, lui, appelle `engine.process` dans le rappel
(`wakeword_porcupine.py`) ; il n'est pas modifié ici, et le choix entre les
deux n'est fait qu'à la composition (`jarvis.runtime.simple_wake_word`).

Trois étages, un seul sens de circulation

1. le **rappel PortAudio** ne fait que copier le bloc (`bytes(indata)`) dans une
   file bornée par `put_nowait`. Pleine, il compte la perte
   (`pcm_blocks_dropped`) et revient : il ne bloque jamais, ne journalise pas,
   n'attend rien ;
2. un **thread consommateur** dédié rééchantillonne à la fréquence du moteur si
   le micro tourne à un autre taux (`StreamingPcm16Resampler`, état continu
   d'un bloc à l'autre), découpe en trames de `engine.frame_length`
   (1280 pour openWakeWord) et appelle `engine.process` avec un **tuple
   d'entiers** — la seule forme que `OpenWakeWordEngine` accepte ;
3. la **boucle asyncio** reçoit les détections et les traces par
   `call_soon_threadsafe` ; le journal n'est jamais écrit depuis le rappel ni
   depuis le thread.

Un propriétaire, jamais deux

Le flux est inscrit dans `jarvis.audio.input_ownership` sous
`OWNER_WAKEWORD_OPENWAKEWORD` et libéré sur **toute** sortie, y compris quand
`stop()` ou `close()` du flux lèvent. `suspend_for_active_session()` ferme le
flux (et libère le moteur : rien de la séance ne survit à la suspension, ni
l'état du modèle ni de la voix) ; `resume()`, appelé en fin de `mute()`, le
rouvre. Un verrou sérialise ouverture et fermeture : `start()` et `resume()`
concurrents n'ouvrent jamais deux flux. Pas de hot-plug en v1 : le périphérique
est celui choisi au démarrage.

Panne dite, jamais fatale

`docs/03-implementation-strategy.md` : une panne du détecteur se dit et laisse la
touche manuelle utilisable. Aucune méthode publique ne lève à cause du moteur
ou du périphérique ; tout passe par une ligne de journal de code stable :

- `wake_engine_unavailable` (+ `cause_code` : paquet ou modèle absent, modèle
  altéré, configuration refusée) : le moteur ne se construit pas. Le flux
  n'est **pas ouvert** (`engine_failed`). La panne n'est **pas définitive** :
  chaque `resume()` retente la construction, une fois, jamais en boucle (une
  panne transitoire au `mute()` ne coupe pas le mot d'éveil pour la séance) ;
- `wake_engine_failed` (+ `cause_code`) : l'inférence a levé en cours de
  séance. Le flux est fermé et libéré, le détecteur s'arrête jusqu'au prochain
  `resume()`, qui reconstruit un moteur neuf. `detections()` reste ouvert
  pendant la panne (il ne se termine qu'à `close()`) : c'est ce qui permet au
  `resume()` de rendre le détecteur utile dans la même séance ;
- `wake_input_unavailable` : `sounddevice` ou le périphérique refuse. Le moteur
  construit pour rien est libéré ; le prochain `resume()` réessaie ;
- `wake_input_close_failed` (warning) : le flux a refusé de se fermer ; le
  propriétaire est quand même libéré ;
- `wake_pcm_dropped` (warning) : la file bornée a perdu des blocs ;
- `wake_consumer_stuck` (warning) : le thread d'inférence ne s'est pas arrêté.

Une trace d'échec identique (même code, même `cause_code`) n'est dite qu'une
fois par `FAILURE_TRACE_EVERY_S` ; les répétitions sont comptées (`suppressed`
sur la trace suivante) et un succès rétablit l'état normal.

Rien n'est persisté : ni fichier, ni trace d'audio ; les traces ne portent que
des scalaires (code, mot, fournisseur, score, seuil, compteurs).
"""

from __future__ import annotations

import asyncio
import math
import queue
import struct
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from jarvis.audio.input_ownership import (
    OWNER_WAKEWORD_OPENWAKEWORD,
    register_input_stream,
    release_input_stream,
)
from jarvis.audio.resampling import StreamingPcm16Resampler
from jarvis.ports.v2 import DiagnosticSink

_BYTES_PER_SAMPLE = 2  # int16 mono

#: Profondeur de la file entre le rappel et le consommateur, en blocs. Au-delà,
#: on perd le plus récent (`put_nowait`) et on le compte : un détecteur en
#: retard ne doit pas servir au moteur un arriéré qui reconnaîtrait un mot
#: d'éveil vieux de plusieurs secondes. 16 blocs = environ 1,3 s de parole.
PCM_QUEUE_BLOCKS = 16

#: Profondeur de la file de détections (même valeur que `CompositeWakeWordBackend`).
DETECTION_QUEUE_SIZE = 4

#: Délai d'attente du consommateur sur une file vide : c'est aussi le temps
#: maximal pour qu'il remarque la demande d'arrêt.
POLL_S = 0.05

#: Temps accordé au thread d'inférence pour s'arrêter à la suspension.
JOIN_TIMEOUT_S = 2.0

#: Les pertes de blocs sont dites au plus une fois par ce délai (la première
#: tout de suite) ; le total figure de toute façon dans la ligne d'arrêt.
DROP_REPORT_EVERY_S = 5.0

#: Une trace d'échec identique est dite au plus une fois par ce délai : un
#: modèle absent ne doit pas produire une ligne à chaque `mute()`.
FAILURE_TRACE_EVERY_S = 60.0

_END = object()


class _Run:
    """Une ouverture du détecteur : file, drapeaux et thread qui lui appartiennent."""

    __slots__ = ("pcm", "stop", "accepting", "thread", "engine", "carry", "resampler", "rate_in")

    def __init__(self, engine: Any, carry: bytearray) -> None:
        self.pcm: queue.Queue[bytes] = queue.Queue(maxsize=PCM_QUEUE_BLOCKS)
        self.stop = threading.Event()
        self.accepting = True
        self.thread: threading.Thread | None = None
        self.engine = engine
        self.carry = carry
        self.resampler: StreamingPcm16Resampler | None = None
        self.rate_in = int(engine.sample_rate)


def detection_trace_data(engine: object, keyword: str, provider: str | None) -> dict[str, object]:
    """Fournisseur, score et seuil lus sur le moteur (duck-typing), scalaires seulement.

    Même contenu que `wake.shared_pcm.detected` (Slice 04) : le port
    `WakeWordBackend` ne transporte que des chaînes, la confiance reste sur le
    moteur. Un moteur sans score (Porcupine) n'en porte pas.
    """

    data: dict[str, object] = {"keyword": keyword}

    # Une trace ne fait jamais perdre la détection : toute lecture qui lève est
    # omise, et seul un flottant fini part dans le journal (JSON valide).
    def read(attr: str) -> object:
        try:
            return getattr(engine, attr, None)
        except Exception:  # noqa: BLE001 - la trace est accessoire
            return None

    name = read("provider") or provider
    if name:
        data["provider"] = str(name)
    for key, attr in (("score", "last_score"), ("threshold", "threshold")):
        value = read(attr)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                if math.isfinite(value):
                    data[key] = round(float(value), 4)
            except (OverflowError, ValueError):  # entier démesuré
                pass
    return data


class OwnStreamWakeWordBackend:
    """`WakeWordBackend` qui ouvre son propre micro et fait l'inférence hors rappel."""

    def __init__(
        self,
        *,
        engine_factory: Callable[[], Any],
        keyword: str = "hey_jarvis",
        provider: str | None = None,
        device: int | str | None = None,
        fallback_sample_rate: int | None = None,
        journal: DiagnosticSink | None = None,
        owner: str = OWNER_WAKEWORD_OPENWAKEWORD,
    ) -> None:
        self.engine_factory = engine_factory
        self.keyword = keyword
        self.provider = provider
        self.device = device
        #: Taux essayé si le périphérique refuse celui du moteur (16 kHz) : la
        #: conversion se fait alors dans le consommateur, jamais dans le rappel.
        self.fallback_sample_rate = fallback_sample_rate
        self.journal = journal
        self.owner = owner
        self.join_timeout_s = JOIN_TIMEOUT_S
        #: Observables depuis l'extérieur : une panne se constate, pas seulement se lit.
        self.engine_failed = False
        self.failure_code: str | None = None
        self.detections_count = 0
        self.frames_processed = 0
        self.pcm_blocks_dropped = 0
        self.input_status_flags = 0
        #: Détections écartées (file pleine) ou jetées (suspension) : dites, jamais silencieuses.
        self.dropped = 0
        self.discarded = 0
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=DETECTION_QUEUE_SIZE)
        #: Mesures (`provider`, `score`, `threshold`, sans le mot-clé) du mot que
        #: `detections()` vient de rendre, comme `SharedPcmWakeWordBackend`. La file
        #: porte des paires `(mot, mesure)` : la mesure est écrite au moment où le mot
        #: est rendu, jamais au moment où le moteur détecte.
        self.last_detection: dict[str, object] | None = None
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream: Any = None
        self._run: _Run | None = None
        self._pcm: queue.Queue[bytes] | None = None
        self._carry = bytearray()
        self._teardown: asyncio.Task[None] | None = None
        self._closed = False
        #: Horloge des traces d'échec (injectable en test).
        self.clock: Callable[[], float] = time.monotonic
        self._failure_seen: dict[tuple[str, str | None], tuple[float, int]] = {}

    # -- traces (boucle asyncio seulement) --------------------------------

    def _trace(self, kind: str, message: str, *, level: str = "info", **data: object) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - un journal en panne ne doit pas tuer le détecteur
            pass

    def _post(self, callback: Callable[..., None], *args: object) -> None:
        """Passer du thread consommateur à la boucle ; muet si la boucle se ferme."""

        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:
            pass

    # -- cycle de vie ------------------------------------------------------

    async def start(self) -> None:
        async with self._lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        # `engine_failed` ne bloque plus : chaque start()/resume() retente la
        # construction, une seule fois (borne documentée, pas de boucle).
        if self._closed or self._stream is not None:
            return
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            # Avant de construire le moteur : inutile de charger un modèle pour rien.
            self._input_failed(exc)
            return
        self._loop = asyncio.get_running_loop()
        try:
            engine = await self._build_engine()
        except Exception as exc:  # noqa: BLE001 - dit, jamais fatal
            self._engine_failed("wake_engine_unavailable", exc)
            return
        # Le moteur est construit : l'état normal est rétabli, quoi qu'il arrive
        # ensuite au micro (une panne de périphérique n'est pas une panne moteur).
        self.engine_failed = False
        self.failure_code = None
        self._failure_seen.clear()
        if self._closed:
            self._delete_engine(engine)
            return
        run = _Run(engine, self._carry)
        stream = self._open_with_fallback(sd, engine, run)
        if stream is None:
            self._delete_engine(engine)
            return
        self._stream, self._run, self._pcm = stream, run, run.pcm
        run.thread = threading.Thread(
            target=self._consume, args=(run,), name="jarvis-wake-own-stream", daemon=True,
        )
        run.thread.start()
        self._trace(
            "wake.own_stream.started",
            "Détection du mot d'éveil à flux propre démarrée",
            keyword=self.keyword,
            **({"provider": self.provider} if self.provider else {}),
            engine_sample_rate=int(engine.sample_rate),
            stream_sample_rate=run.rate_in,
            resampled=run.rate_in != int(engine.sample_rate),
        )

    async def _build_engine(self) -> Any:
        """Construire le moteur dans un thread, sans jamais le laisser fuir.

        Si la tâche est annulée pendant la construction (arrêt pendant le
        premier chargement), le thread finit quand même : le moteur qu'il rend
        n'a plus de destinataire. Exactement un des deux côtés le supprime, selon
        qui arrive le dernier sous le verrou.
        """

        lock = threading.Lock()
        state: dict[str, Any] = {"abandoned": False, "engine": None}

        def work() -> None:
            engine = self.engine_factory()
            with lock:
                abandoned = state["abandoned"]
                if not abandoned:
                    state["engine"] = engine
            if abandoned:
                self._delete_engine(engine, from_thread=True)

        try:
            await asyncio.to_thread(work)
        except asyncio.CancelledError:
            with lock:
                state["abandoned"] = True
                orphan, state["engine"] = state["engine"], None
            if orphan is not None:
                self._delete_engine(orphan)
            raise
        with lock:
            engine, state["engine"] = state["engine"], None
        return engine

    def _open_with_fallback(self, sd: Any, engine: Any, run: _Run) -> Any:
        engine_rate = int(engine.sample_rate)
        rates = [engine_rate]
        if self.fallback_sample_rate and int(self.fallback_sample_rate) != engine_rate:
            rates.append(int(self.fallback_sample_rate))
        last: BaseException | None = None
        for rate in rates:
            try:
                stream = self._open_stream(sd, engine, run, rate)
            except Exception as exc:  # noqa: BLE001 - on essaie le taux suivant, puis on le dit
                last = exc
                continue
            run.rate_in = rate
            run.resampler = (
                None if rate == engine_rate
                else StreamingPcm16Resampler(source_rate=rate, target_rate=engine_rate)
            )
            return stream
        assert last is not None
        self._input_failed(last)
        return None

    def _open_stream(self, sd: Any, engine: Any, run: _Run, rate: int) -> Any:
        frame_length = int(engine.frame_length)
        blocksize = max(1, round(frame_length * rate / int(engine.sample_rate)))

        def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            # Rien d'autre que copier et mettre en file : pas d'inférence, pas de
            # journal, pas de verrou, pas d'attente. Ne lève jamais.
            del frames, time_info
            if not run.accepting:
                return
            try:
                if status:
                    self.input_status_flags += 1
                run.pcm.put_nowait(bytes(indata))
            except queue.Full:
                self.pcm_blocks_dropped += 1
            except Exception:  # noqa: BLE001 - lever depuis PortAudio ferait tomber le flux
                return

        stream = sd.RawInputStream(
            samplerate=rate, channels=1, dtype="int16", device=self.device,
            blocksize=blocksize, callback=callback,
        )
        register_input_stream(self.owner, stream, label=str(self.device))
        try:
            stream.start()
        except BaseException:
            self._close_stream(stream)
            raise
        return stream

    def _close_stream(self, stream: Any) -> None:
        """Fermer un flux, dire l'échec, et **toujours** rendre le propriétaire."""

        failure: BaseException | None = None
        try:
            for step in (stream.stop, stream.close):
                try:
                    step()
                except Exception as exc:  # noqa: BLE001 - chaque étape est tentée
                    failure = failure or exc
        finally:
            # Le périphérique est rendu dans tous les cas ; le registre doit le
            # dire, sinon une fermeture ratée laisserait un propriétaire fantôme.
            release_input_stream(stream)
        if failure is not None:
            self._trace(
                "wake.own_stream.input_close_failed",
                f"Fermeture du flux d'écoute en échec ({type(failure).__name__}) : propriétaire libéré.",
                level="warning", code="wake_input_close_failed", keyword=self.keyword,
            )

    # -- consommateur (thread dédié, jamais le rappel, jamais la boucle) ----

    def _consume(self, run: _Run) -> None:
        engine = run.engine
        frame_length = int(engine.frame_length)
        frame_bytes = frame_length * _BYTES_PER_SAMPLE
        unpack = "h" * frame_length
        carry = run.carry
        reported_drops = 0
        last_report = -DROP_REPORT_EVERY_S
        try:
            while not run.stop.is_set():
                try:
                    block = run.pcm.get(timeout=POLL_S)
                except queue.Empty:
                    continue
                if run.resampler is not None:
                    block = run.resampler.process(block)
                carry.extend(block)
                while len(carry) >= frame_bytes and not run.stop.is_set():
                    frame = struct.unpack_from(unpack, carry, 0)  # tuple d'entiers
                    del carry[:frame_bytes]
                    try:
                        detected = engine.process(frame)
                    except Exception as exc:  # noqa: BLE001 - dit puis arrêt propre
                        self._post(self._on_engine_failure, run, "wake_engine_failed", exc)
                        return
                    self.frames_processed += 1
                    if detected is not None and detected >= 0:
                        self._post(
                            self._on_detected, run,
                            detection_trace_data(engine, self.keyword, self.provider),
                        )
                dropped = self.pcm_blocks_dropped
                now = time.monotonic()
                if dropped != reported_drops and now - last_report >= DROP_REPORT_EVERY_S:
                    reported_drops, last_report = dropped, now
                    self._post(self._say_drops, dropped)
        except Exception as exc:  # noqa: BLE001 - rééchantillonnage ou découpage : dit aussi
            self._post(self._on_engine_failure, run, "wake_consume_failed", exc)

    def _say_drops(self, total: int) -> None:
        self._trace(
            "wake.own_stream.dropped",
            "Blocs audio perdus : le détecteur est en retard sur la capture",
            level="warning", code="wake_pcm_dropped", pcm_blocks_dropped=total,
        )

    # -- événements (boucle asyncio) ----------------------------------------

    def _on_detected(self, run: _Run, data: dict[str, object]) -> None:
        if run is not self._run or not run.accepting:
            # Une détection arrivée après la suspension appartient à la séance
            # d'avant : la jeter, et le dire par le compteur.
            self.discarded += 1
            return
        self.detections_count += 1
        self._trace("wake.own_stream.detected", "Mot d'éveil reconnu", **data)
        if self._queue.full():
            self.dropped += 1
            self._trace(
                "wake.own_stream.detection_dropped",
                "Mot d'éveil écarté : la file de déclencheurs est pleine",
                level="warning", code="wake_detection_dropped", dropped=self.dropped,
            )
            return
        self._queue.put_nowait((self.keyword, {key: value for key, value in data.items() if key != "keyword"}))

    def _on_engine_failure(self, run: _Run, code: str, exc: BaseException) -> None:
        if run is not self._run:
            return
        self._engine_failed(code, exc)
        # Fermer le micro depuis une tâche : on est dans un callback synchrone.
        self._teardown = asyncio.ensure_future(self.suspend())

    def _engine_failed(self, code: str, exc: BaseException) -> None:
        """Dire la panne du moteur, l'enregistrer, débloquer `detections()`."""

        self.engine_failed = True
        self.failure_code = code
        cause = getattr(exc, "cause_code", None) or getattr(exc, "code", None)
        extra: dict[str, object] = {}
        if isinstance(cause, str) and cause and cause != code:
            extra["cause_code"] = cause
        if self.provider:
            extra["provider"] = self.provider
        self._trace_failure(
            (code, extra.get("cause_code")),  # type: ignore[arg-type]
            f"Détection du mot d'éveil hors service : {type(exc).__name__}: {exc}. "
            "La touche manuelle reste utilisable.",
            code=code, keyword=self.keyword, **extra,
        )

    def _input_failed(self, exc: BaseException) -> None:
        self._trace_failure(
            ("wake_input_unavailable", None),
            f"Écoute du micro impossible pour le mot d'éveil : {type(exc).__name__}: {exc}. "
            "La touche manuelle reste utilisable.",
            code="wake_input_unavailable", keyword=self.keyword,
            **({"provider": self.provider} if self.provider else {}),
        )

    def _trace_failure(self, key: tuple[str, str | None], message: str, **data: object) -> None:
        """Dire un échec, mais une trace identique au plus une fois par minute."""

        now = self.clock()
        seen = self._failure_seen.get(key)
        if seen is not None and now - seen[0] < FAILURE_TRACE_EVERY_S:
            self._failure_seen[key] = (seen[0], seen[1] + 1)
            return
        suppressed = seen[1] if seen is not None else 0
        self._failure_seen[key] = (now, 0)
        if suppressed:
            data["suppressed"] = suppressed
        self._trace("wake.own_stream.failed", message, level="error", **data)

    def _signal(self, token: object) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - full() vient d'être vrai
                pass
        self._queue.put_nowait(token)

    # -- WakeWordBackend ---------------------------------------------------

    async def suspend(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def suspend_for_active_session(self) -> None:
        await self.suspend()

    async def resume(self) -> None:
        if not self._closed:
            await self.start()

    async def detections(self) -> AsyncIterator[str]:
        await self.start()
        while not self._closed:
            item = await self._queue.get()
            if item is _END:
                return
            keyword, measures = item  # type: ignore[misc]
            self.last_detection = measures
            yield str(keyword)

    async def close(self) -> None:
        self._closed = True
        await self.suspend()
        self._signal(_END)

    async def _stop_locked(self) -> None:
        run, self._run = self._run, None
        stream, self._stream = self._stream, None
        self._pcm = None
        if run is not None:
            run.accepting = False
        # Le micro d'abord : c'est lui qui doit être rendu avant tout le reste.
        if stream is not None:
            self._close_stream(stream)
        # Rien d'une détection d'avant la suspension ne doit survivre.
        while not self._queue.empty():
            token = self._queue.get_nowait()
            if token is _END:
                self._queue.put_nowait(token)
                break
            self.discarded += 1
        if run is None:
            return
        run.stop.set()
        thread = run.thread
        stuck = False
        if thread is not None:
            await asyncio.to_thread(thread.join, self.join_timeout_s)
            stuck = thread.is_alive()
        if stuck:
            self._trace(
                "wake.own_stream.consumer_stuck",
                "Le thread d'inférence ne s'est pas arrêté : moteur laissé en place.",
                level="warning", code="wake_consumer_stuck", keyword=self.keyword,
            )
        else:
            run.carry.clear()
            while True:
                try:
                    run.pcm.get_nowait()
                except queue.Empty:
                    break
            self._delete_engine(run.engine)
        self._trace(
            "wake.own_stream.stopped",
            "Détection du mot d'éveil à flux propre arrêtée",
            keyword=self.keyword, frames=self.frames_processed,
            detections=self.detections_count, pcm_blocks_dropped=self.pcm_blocks_dropped,
        )

    def _delete_engine(self, engine: Any, *, from_thread: bool = False) -> None:
        try:
            engine.delete()
        except Exception as exc:  # noqa: BLE001 - libération au mieux
            message = f"Libération du moteur en échec : {type(exc).__name__}"
            if from_thread:  # le journal ne s'écrit que depuis la boucle
                self._post(self._say_delete_failed, message)
            else:
                self._say_delete_failed(message)

    def _say_delete_failed(self, message: str) -> None:
        self._trace(
            "wake.own_stream.engine_delete_failed", message,
            level="warning", code="wake_engine_delete_failed", keyword=self.keyword,
        )
