"""Propriétaire des captures dans Core (handoff session-context-recording, Slice 05 ; D13, D-CAP).

`CaptureService` est la **seule** vérité d'état des captures explicites
(audio, écran, capture d'écran) : machine d'état, intention durable (table
`captures`, v7), finalisation dans le registre d'Artifacts, activité de
Session et réconciliation après la mort de Core. Le cerveau, MCP et
l'interface sont des clients ; aucun d'eux ne porte la durée de vie d'une
capture, et un état optimiste d'interface n'est jamais une vérité. Core ouvre
les sources lui-même (D-CAP) : la mort du cerveau, du Control Center ou de
Voice n'interrompt pas une capture. Contrat : `docs/capture.md`.

Règles tenues ici :

- une capture continue par canal/appareil (`already_active`) ; des canaux
  différents (audio + écran) tournent ensemble ;
- démarrage : ligne `starting`, Artifact `pending` (même Session/Context que
  la capture, pris au **démarrage**), spool ouvert, source démarrée sous
  échéance, puis `active` + `capture.started` (même transaction) ;
- arrêt idempotent et à vol unique : deux `stop` concurrents attendent le
  même arrêt ; un arrêt pendant `starting` attend la fin du démarrage puis
  arrête ; après la fin, `stop` rend l'état final sans rien refaire ;
- une perte (source perdue, disque plein, écriture refusée) arrête la
  capture ; un trou daté écrit `capture.gap` ; la preuve n'est `complete` que
  si le payload final est sur disque sans erreur ni trou, sinon `partial`
  (octets présents) ou `failed` — jamais un `complete` silencieux ;
- reprise au démarrage de Core (`recover`, **avant**
  `ArtifactService.recover_pending`) : toute capture restée ouverte d'une vie
  précédente reçoit la réparation de sa famille (`CaptureRepair`), puis son
  Artifact est repris (`partial`/`failed`), `capture.gap` et
  `capture.stopped` sont écrits ; aucune capture n'est relancée ;
- perte bornée en cas de mort de Core : le propriétaire remet le spool au
  système toutes les `FLUSH_INTERVAL_S` (et le tampon du spool ne dépasse
  jamais 64 Kio), `fsync` toutes les `FSYNC_INTERVAL_S` (fichier d'un
  encodeur externe compris, refus non fatal) et dès que la source est arrêtée ;
  `bytes_written` du statut ne compte que les octets remis au système ;
- le disque n'est jamais touché depuis la boucle : `checkpoint`, `finalize`
  et `close` du sink tournent dans un fil ;
- une base qui refuse pendant un arrêt ne perd pas la capture : elle reste
  visible (`status().stuck`), garde son appareil, et l'arrêt se rejoue au
  `stop` suivant, au prochain `start` du même appareil ou à la fermeture ;
  l'erreur rendue a un code stable (`storage_unavailable`/`storage_full`) ;
- miroir diagnostic `core.capture.*` : identifiants, états, codes et
  comptes seulement, jamais de média.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import errno
import os
from pathlib import Path
import threading
import time
from typing import Any

from jarvis.core.artifact_service import ArtifactService
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactErrorCode, ArtifactState
from jarvis.domain.capture import (
    DEFAULT_DEVICE, CaptureChannel, CaptureError, CaptureErrorCode, CaptureMode, CaptureRecord, CaptureState,
    StopReason, activate, artifact_kind_of, attach_artifact, check_capture_id, finish, new_capture, request_stop,
)
from jarvis.domain.session_activity import ActivityDraft, ActivityKind
from jarvis.domain.v2 import utc_now
from jarvis.ports.artifacts import ArtifactPayloadError, ArtifactSpool
from jarvis.ports.capture import (
    CaptureRepair, CaptureRepository, CaptureSource, CaptureSourceError, CaptureSourceRegistry, MediaInfo,
    OneShotSource, RepairOutcome, RepairTarget,
)
from jarvis.ports.v2 import DiagnosticSink
from jarvis.ports.workspace_board import BoardStoreError

DEFAULT_START_TIMEOUT_S = 15.0
DEFAULT_STOP_TIMEOUT_S = 10.0
#: Cadence du propriétaire : spool remis au système (survit à la mort de Core)...
FLUSH_INTERVAL_S = 1.0
#: ... et poussé sur disque (`fsync`, survit à une coupure). Mesuré sur l'hôte : `flush` d'1 s
#: d'audio (32 Ko) ≈ 0,02 ms, `fsync` de 5 s (160 Ko) ≈ 0,9 ms (max 1,6 ms).
FSYNC_INTERVAL_S = 5.0
#: Échéance d'une réparation de famille au démarrage : une réparation bloquée ne retient pas Core.
DEFAULT_REPAIR_TIMEOUT_S = 45.0
#: Captures ouvertes réconciliées par lot au démarrage.
RECOVERY_BATCH = 64
RECENT_LIMIT = 20

_DISK_FULL_ERRNOS = frozenset({errno.ENOSPC, *([errno.EDQUOT] if hasattr(errno, "EDQUOT") else [])})
#: ERROR_HANDLE_DISK_FULL (39), ERROR_DISK_FULL (112).
_DISK_FULL_WINERRORS = frozenset({39, 112})
#: SQLITE_FULL (code primaire) et son message exact.
_SQLITE_FULL = 13
_SQLITE_FULL_MESSAGE = "database or disk is full"


def storage_code(exc: BaseException, default: CaptureErrorCode) -> CaptureErrorCode:
    """`storage_full` si la chaîne de causes contient un disque plein (OS ou SQLite), sinon `default`."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and (current.errno in _DISK_FULL_ERRNOS
                                             or getattr(current, "winerror", None) in _DISK_FULL_WINERRORS):
            return CaptureErrorCode.STORAGE_FULL
        # `sqlite3.Error` sans l'importer (Core ne dépend d'aucun adaptateur) : son code d'erreur suffit.
        sqlite_code = getattr(current, "sqlite_errorcode", None)
        if isinstance(sqlite_code, int) and sqlite_code & 0xFF == _SQLITE_FULL:
            return CaptureErrorCode.STORAGE_FULL
        if isinstance(current, BoardStoreError) and _SQLITE_FULL_MESSAGE in str(current):
            return CaptureErrorCode.STORAGE_FULL
        current = current.__cause__ or current.__context__
    return default


def failure_code(exc: BaseException, default: CaptureErrorCode = CaptureErrorCode.STORAGE_UNAVAILABLE
                 ) -> CaptureErrorCode:
    """Code stable d'un échec hors règle (base, registre) : le sien pour une `CaptureError`, sinon stockage."""

    return exc.code if isinstance(exc, CaptureError) else storage_code(exc, default)


def _in_daemon_thread(fn: Callable[..., Any], *args: Any) -> asyncio.Future[Any]:
    """`fn(*args)` dans un fil démon (pas l'exécuteur par défaut : un fil bloqué n'y retiendrait pas
    l'arrêt de la boucle) ; le futur rendu porte son résultat ou son exception."""

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()

    def settle(result: Any, error: BaseException | None) -> None:
        if future.done():
            return  # abandonné (échéance) : le résultat tardif est ignoré
        if error is None:
            future.set_result(result)
        else:
            future.set_exception(error)

    def work() -> None:
        try:
            result, error = fn(*args), None
        except BaseException as exc:  # noqa: BLE001 - handed to the awaiting coroutine, never lost
            result, error = None, exc
        try:
            loop.call_soon_threadsafe(settle, result, error)
        except RuntimeError:
            pass  # intentional: loop closed (Core gone) — nobody waits for this repair any more

    threading.Thread(target=work, name="capture-repair", daemon=True).start()
    return future


@dataclass(frozen=True, slots=True)
class CaptureAssociation:
    """Session et Context actifs au démarrage d'une capture (fournis par `SessionManager`)."""

    jarvis_session_id: str
    context_id: str | None


@dataclass(frozen=True, slots=True)
class CaptureOptions:
    source: str | None = None
    device: str = DEFAULT_DEVICE
    #: Petits scalaires d'acquisition (≤ 16), copiés dans la ligne `captures`.
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaptureRecoveryReport:
    partial: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    #: Arrêt déjà fini côté Artifact (la mort a frappé entre les deux écritures).
    complete: tuple[str, ...] = ()
    repair_failed: tuple[str, ...] = ()
    #: Lignes illisibles ou dont la reprise a échoué : laissées ouvertes, journalisées, réessayées au
    #: prochain démarrage (ou au `start` qui bute sur elles) ; les autres captures sont reprises quand même.
    unreadable: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {"partial": list(self.partial), "failed": list(self.failed), "complete": list(self.complete),
                "repair_failed": list(self.repair_failed), "unreadable": list(self.unreadable)}


@dataclass(frozen=True, slots=True)
class StuckCapture:
    """Arrêt commencé que la base (ou le registre) a refusé de terminer : la capture reste ouverte."""

    capture_id: str
    error_code: CaptureErrorCode
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {"capture_id": self.capture_id, "error_code": self.error_code.value, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class CaptureStatus:
    """Vérité d'état : captures ouvertes (octets et trous en direct), arrêts bloqués, dernière réconciliation.

    `bytes_written` d'une capture ouverte = octets remis au système (survivent à la mort de Core) ;
    il suit l'écriture avec au plus `FLUSH_INTERVAL_S` de retard.
    """

    captures: tuple[CaptureRecord, ...]
    recovery: CaptureRecoveryReport | None
    #: Captures dont l'arrêt attend une base disponible (elles figurent aussi dans `captures`).
    stuck: tuple[StuckCapture, ...] = ()

    def active_on(self, channel: CaptureChannel) -> tuple[CaptureRecord, ...]:
        return tuple(r for r in self.captures if r.channel is channel)

    def to_payload(self) -> dict[str, Any]:
        return {"captures": [r.to_payload() for r in self.captures],
                "recovery": None if self.recovery is None else self.recovery.to_payload(),
                "stuck": [s.to_payload() for s in self.stuck]}


class NoCaptureSources:
    """Registre vide : aucune source installée (les adaptateurs réels arrivent aux Slices 06 et 07)."""

    def _refuse(self, channel: CaptureChannel) -> CaptureError:
        return CaptureError(CaptureErrorCode.UNSUPPORTED_SOURCE,
                            f"no capture source is installed for channel {CaptureChannel(channel).value}")

    def continuous(self, channel: CaptureChannel, *, source: str | None, device: str) -> CaptureSource:
        raise self._refuse(channel)

    def one_shot(self, channel: CaptureChannel, *, source: str | None, device: str) -> OneShotSource:
        raise self._refuse(channel)

    def source_name(self, channel: CaptureChannel, mode: CaptureMode, source: str | None) -> str:
        raise self._refuse(channel)


class SpoolCaptureSink:
    """`CaptureSink` d'une capture : écrit dans le spool de son Artifact, rapporte trous et pertes.

    Les écritures sont protégées par un verrou de fil (la source réelle écrit
    depuis son propre fil) ; après `finalize`/`close`, toute écriture est
    refusée (`write_failed`) : une source lente à s'arrêter ne peut plus
    toucher un payload finalisé. Trous et pertes sont remis à la boucle de Core
    (`call_soon_threadsafe`).
    """

    def __init__(self, spool: ArtifactSpool, *, loop: asyncio.AbstractEventLoop,
                 on_gap: Callable[[str, int | None], None],
                 on_failure: Callable[[CaptureErrorCode, str], None]) -> None:
        self._spool = spool
        self._loop = loop
        self._on_gap = on_gap
        self._on_failure = on_failure
        self._lock = threading.Lock()
        self._closed = False
        self._failed: CaptureErrorCode | None = None
        #: Après `hand_over` : l'encodeur externe écrit et vide lui-même ses tampons (Slice 07).
        self._external = False

    @property
    def bytes_written(self) -> int:
        """Octets remis au système : ce qui survit à la mort de Core (le statut ne montre que ceux-là)."""

        return self._spool.flushed_size

    @property
    def bytes_accepted(self) -> int:
        """Octets acceptés par le spool, tampon du processus compris."""

        return self._spool.size

    def checkpoint(self, *, durable: bool) -> str | None:
        """Cadence du propriétaire : tampon remis au système, plus `fsync` si `durable`.

        Sans effet sur un sink fermé ou en échec ; un refus du disque est un
        échec de stockage comme une écriture refusée (la capture s'arrête).
        Écrivain externe (ffmpeg remet déjà chaque paquet au système,
        `-flush_packets 1`) : seul le `fsync` reste à faire ; le fichier de
        l'encodeur est rouvert pour cela, et un refus (partage, `OSError`) n'est
        **pas** fatal — il est rendu (raison) pour que le propriétaire le
        journalise, l'enregistrement continue. Appelé depuis un fil, jamais
        depuis la boucle.
        """

        with self._lock:
            if self._closed or self._failed is not None:
                return None
            if self._external:
                if not durable:
                    return None
                try:
                    self._spool.sync()
                except (ArtifactPayloadError, OSError) as exc:
                    return f"{type(exc).__name__}: {str(exc)[:200]}"
                return None
        self._io(self._spool.sync if durable else self._spool.flush)
        return None

    def _io(self, action: Callable[..., Any], *args: Any) -> Any:
        with self._lock:
            if self._failed is not None:
                raise CaptureSourceError(self._failed, "capture sink already failed")
            if self._closed:
                raise CaptureSourceError(CaptureErrorCode.WRITE_FAILED, "capture sink is closed")
            try:
                return action(*args)
            except ArtifactPayloadError as exc:
                code = storage_code(exc, CaptureErrorCode.WRITE_FAILED)
                self._failed = code
                failure = exc
        self._post(self._on_failure, code, f"{failure.code}: {str(failure)[:200]}")
        raise CaptureSourceError(code, str(failure)[:300]) from failure

    def write(self, data: bytes) -> None:
        self._io(self._spool.write, bytes(data))

    def write_at(self, offset: int, data: bytes) -> None:
        self._io(self._spool.write_at, offset, bytes(data))

    def hand_over(self) -> Path:
        """`.partial` confié à un encodeur externe (enregistrement d'écran, Slice 07)."""

        path = self._io(self._spool.hand_over)
        self._external = True
        return path

    def sync(self) -> None:
        self._io(self._spool.sync)

    def gap(self, *, reason: str, lost_ms: int | None = None) -> None:
        self._post(self._on_gap, str(reason)[:64], lost_ms)

    def lost(self, code: CaptureErrorCode, reason: str) -> None:
        self._post(self._on_failure, CaptureErrorCode(code), str(reason)[:200])

    def finalize(self) -> int:
        """`fsync` + renommage du spool ; plus aucune écriture ensuite. `ArtifactPayloadError` si refusé."""

        with self._lock:
            self._closed = True
            return self._spool.finalize()

    def close(self) -> None:
        """Ferme sans finaliser (le `.partial` reste, preuve). `ArtifactPayloadError` si la fermeture échoue."""

        with self._lock:
            self._closed = True
            self._spool.close()

    def _post(self, fn: Callable[..., None], *args: Any) -> None:
        try:
            self._loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:
            # intentional: boucle de Core fermée (Core meurt) — la réconciliation
            # du prochain démarrage écrit le trou et la fin de cette capture.
            pass


@dataclass(eq=False)
class _Run:
    """Une capture vivante dans cette vie de Core."""

    record: CaptureRecord
    source: CaptureSource | None = None
    sink: SpoolCaptureSink | None = None
    artifact: Artifact | None = None
    source_started: bool = False
    stop_requested: bool = False
    failure: tuple[CaptureErrorCode, str] | None = None
    gaps: int = 0
    lifecycle: asyncio.Lock = field(default_factory=asyncio.Lock)
    write: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop_task: asyncio.Task[None] | None = None
    pending: set[asyncio.Task[Any]] = field(default_factory=set)
    #: Cadence `flush`/`fsync` du propriétaire (vit tant que la source écrit).
    durability: asyncio.Task[None] | None = None
    #: Faits de fin de la source, gardés pour rejouer un arrêt bloqué.
    media: MediaInfo = field(default_factory=MediaInfo)
    #: Issue du payload (finalisé ?, erreur) : faite une seule fois, même si l'arrêt se rejoue.
    payload: tuple[bool, CaptureErrorCode | None] | None = None
    #: Arrêt refusé par la base ou le registre : la capture reste ouverte et visible.
    stuck: StuckCapture | None = None
    stop_reason: StopReason | None = None
    #: `fsync` du fichier de l'encodeur refusé au moins une fois (journalisé une seule fois).
    sync_refused: bool = False


class CaptureService:
    """Propriétaire unique des captures. Voir l'en-tête du module et `docs/capture.md`."""

    def __init__(
        self,
        repository: CaptureRepository,
        artifacts: ArtifactService,
        sources: CaptureSourceRegistry,
        *,
        association: Callable[[], Awaitable[CaptureAssociation]],
        repairs: Mapping[CaptureChannel, CaptureRepair] | None = None,
        diagnostics: DiagnosticSink | None = None,
        clock: Callable[[], datetime] = utc_now,
        start_timeout_s: float = DEFAULT_START_TIMEOUT_S,
        stop_timeout_s: float = DEFAULT_STOP_TIMEOUT_S,
        flush_interval_s: float = FLUSH_INTERVAL_S,
        fsync_interval_s: float = FSYNC_INTERVAL_S,
        repair_timeout_s: float = DEFAULT_REPAIR_TIMEOUT_S,
    ) -> None:
        self._repo = repository
        self._artifacts = artifacts
        self._sources = sources
        self._association = association
        self._repairs = dict(repairs or {})
        self._diagnostics = diagnostics
        self._clock = clock
        self._start_timeout_s = start_timeout_s
        self._stop_timeout_s = stop_timeout_s
        self._flush_interval_s = flush_interval_s
        self._fsync_interval_s = fsync_interval_s
        self._repair_timeout_s = repair_timeout_s
        self._runs: dict[str, _Run] = {}
        self._holders: dict[tuple[CaptureChannel, str], str] = {}
        self._admission = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closing = False
        self._recovery: CaptureRecoveryReport | None = None
        self._started_listeners: list[Callable[[CaptureRecord], Awaitable[None]]] = []
        self._stopped_listeners: list[Callable[[CaptureRecord], Awaitable[None]]] = []

    def add_started_listener(self, listener: Callable[[CaptureRecord], Awaitable[None]]) -> None:
        """Rappel après le commit de `capture.started` (transcription d'un enregistrement audio,
        Slice 06). Lancé dans sa propre tâche : jamais attendu par le démarrage, jamais levé vers lui
        (un échec est journalisé `core.capture.listener_failed`)."""

        self._started_listeners.append(listener)

    def add_stopped_listener(self, listener: Callable[[CaptureRecord], Awaitable[None]]) -> None:
        """Rappel après le commit de `capture.stopped` (rattrapage de la transcription, Slice 06).
        Même contrat que `add_started_listener` : sa propre tâche, jamais levé vers l'arrêt."""

        self._stopped_listeners.append(listener)

    # ------------------------------------------------------------ lecture

    def status(self) -> CaptureStatus:
        """Captures ouvertes de cette vie de Core, avec octets et trous en direct."""

        return CaptureStatus(captures=tuple(self._live(run) for run in self._runs.values() if run.record.is_open),
                             recovery=self._recovery,
                             stuck=tuple(run.stuck for run in self._runs.values() if run.stuck is not None))

    async def get(self, capture_id: str) -> CaptureRecord:
        check_capture_id(capture_id)
        run = self._runs.get(capture_id)
        if run is not None:
            return self._live(run)
        record = await self._repo.get_capture(capture_id)
        if record is None:
            raise CaptureError(CaptureErrorCode.CAPTURE_NOT_FOUND, f"capture {capture_id} does not exist")
        return record

    async def recent(self, *, limit: int = RECENT_LIMIT) -> tuple[CaptureRecord, ...]:
        return tuple(await self._repo.recent_captures(limit=limit))

    @staticmethod
    def _live(run: _Run) -> CaptureRecord:
        if run.sink is None or not run.record.is_open:
            return run.record
        return replace(run.record, bytes_written=run.sink.bytes_written, gaps=run.gaps)

    # ------------------------------------------------------------ démarrage

    async def start(self, channel: CaptureChannel | str, options: CaptureOptions | None = None) -> CaptureRecord:
        """Démarre une capture continue ; rend la ligne `active` (ou `stopping` si un arrêt est déjà venu).

        Refus : `unsupported_*`, `already_active` (capture qui tient le canal
        nommée dans `capture_id`), `capture_association_unavailable`,
        `capture_service_stopping`. Échec de la source ou du stockage : la
        capture et son Artifact finissent `failed` et le code est levé
        (`CaptureError.capture_id` la nomme).
        """

        options = options or CaptureOptions()
        channel = self._channel(channel)
        self._refuse_when_closing()
        try:
            source = self._sources.continuous(channel, source=options.source, device=options.device)
            source_name = self._sources.source_name(channel, CaptureMode.CONTINUOUS, options.source)
        except CaptureError as exc:
            self._refused(channel, exc)
            raise
        async with self._admission:
            self._refuse_when_closing()
            try:
                await self._free_device(channel, options.device)
            except CaptureError as exc:
                self._refused(channel, exc)
                raise
            association = await self._associate()
            record = new_capture(channel=channel, mode=CaptureMode.CONTINUOUS, source=source_name,
                                 device=options.device, now=self._clock(),
                                 jarvis_session_id=association.jarvis_session_id,
                                 context_id=association.context_id, data=options.data)
            try:
                await self._insert(record)
            except CaptureError as exc:
                self._refused(channel, exc)
                raise
            except Exception as exc:  # noqa: BLE001 - base refused: stable code, cause kept in the message
                error = CaptureError(failure_code(exc), f"capture store refused the start: {type(exc).__name__}: "
                                     f"{str(exc)[:200]}")
                self._refused(channel, error)
                raise error from exc
            run = _Run(record=record, source=source)
            self._runs[record.capture_id] = run
            self._holders[record.device_key] = record.capture_id
            # Pris avant de rendre l'admission : un `stop` qui trouve la capture
            # attend la fin de son démarrage.
            await run.lifecycle.acquire()
        task = asyncio.create_task(self._start_flow(run), name=f"capture-start-{record.capture_id}")
        self._track(task)
        return await asyncio.shield(task)

    async def _free_device(self, channel: CaptureChannel, device: str) -> None:
        """Appareil libre, ou `already_active` qui nomme la capture qui le tient.

        Une capture qui le tient encore parce que son arrêt est bloqué (base
        refusée) voit cet arrêt rejoué ici ; s'il échoue encore, son code de
        stockage est levé (avec `capture_id`).
        """

        holder = self._holders.get((channel, device))
        if holder is None:
            return
        run = self._runs.get(holder)
        if run is not None and run.stuck is not None:
            await self._request_stop(run, run.stop_reason or StopReason.USER)
            if self._holders.get((channel, device)) is None:
                return
        raise CaptureError(CaptureErrorCode.ALREADY_ACTIVE, f"capture {holder} already holds {channel.value}/{device}",
                           capture_id=holder)

    async def _insert(self, record: CaptureRecord) -> None:
        """Insertion ; une ligne ouverte d'une vie précédente qui tient l'appareil est réconciliée, puis un
        nouvel essai."""

        try:
            await self._repo.insert_capture(record)
            return
        except CaptureError as exc:
            orphan = exc.capture_id
            if exc.code is not CaptureErrorCode.ALREADY_ACTIVE or orphan is None or orphan in self._runs:
                raise
            if not await self._reconcile_orphan(orphan):
                raise
        await self._repo.insert_capture(record)

    async def _reconcile_orphan(self, capture_id: str) -> bool:
        """Ligne ouverte que cette vie de Core ne fait pas tourner : réconciliée comme au démarrage."""

        try:
            record = await self._repo.get_capture(capture_id)
            if record is None or not record.is_open:
                return True
            state, repair_ok = await self._recover_one(record)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: logged, the caller keeps its already_active refusal
            self._trace("core.capture.orphan_unrecovered", f"Capture orpheline non réconciliée : "
                        f"{type(exc).__name__}: {str(exc)[:200]}", level="error",
                        data={"capture_id": capture_id, "code": failure_code(exc).value,
                              "exception_type": type(exc).__name__})
            return False
        self._trace("core.capture.orphan_recovered", "Capture orpheline réconciliée avant un démarrage",
                    level="warning", data={"capture_id": capture_id, "state": state.value,
                                           "repair_failed": not repair_ok})
        return True

    async def _start_flow(self, run: _Run) -> CaptureRecord:
        try:
            await self._start_run(run)
        except CaptureError as exc:
            if run.record.is_open and run.stuck is None:
                await self._abandon(run, exc)  # refus du magasin en chemin : finir proprement, ou bloquée
            raise
        except Exception as exc:
            await self._abandon(run, exc)
            raise CaptureError(failure_code(exc), f"capture {run.record.capture_id} did not start: "
                               f"{type(exc).__name__}: {str(exc)[:200]}", capture_id=run.record.capture_id) from exc
        finally:
            run.lifecycle.release()
        return run.record

    async def _start_run(self, run: _Run) -> None:
        record = run.record
        source = run.source
        assert source is not None
        try:
            artifact = await self._artifacts.create(
                kind=artifact_kind_of(record.channel, record.mode), source=f"capture.{record.channel.value}",
                jarvis_session_id=record.jarvis_session_id, context_id=record.context_id,
                payload_name=source.payload_name, started_at=record.created_at, mime_type=source.mime_type,
                metadata={"capture_id": record.capture_id, "device": record.device, "capture_source": record.source},
                capture_id=record.capture_id)
        except ArtifactError as exc:
            await self._fail_start(run, CaptureErrorCode.STORAGE_UNAVAILABLE, f"{exc.code}: {str(exc)[:200]}")
        run.artifact = artifact
        await self._save(run, lambda r: attach_artifact(r, artifact.artifact_id, now=self._clock()))
        try:
            spool = self._artifacts.open_spool(artifact)
        except ArtifactPayloadError as exc:
            await self._fail_start(run, storage_code(exc, CaptureErrorCode.STORAGE_UNAVAILABLE),
                                   f"{exc.code}: {str(exc)[:200]}")
        loop = asyncio.get_running_loop()
        run.sink = SpoolCaptureSink(spool, loop=loop, on_gap=lambda reason, lost_ms: self._on_gap(run, reason, lost_ms),
                                    on_failure=lambda code, reason: self._on_failure(run, code, reason))
        begun = time.perf_counter()
        try:
            await asyncio.wait_for(source.start(run.sink), self._start_timeout_s)
            run.source_started = True
            run.durability = asyncio.create_task(self._durability(run),
                                                 name=f"capture-durability-{run.record.capture_id}")
        except CaptureSourceError as exc:
            await self._fail_start(run, exc.code, str(exc)[:200])
        except TimeoutError:
            await self._stop_source_quietly(run)
            await self._fail_start(run, CaptureErrorCode.SOURCE_TIMEOUT,
                                   f"source did not start within {self._start_timeout_s:g} s")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - said with its type, the capture fails with a stable code
            await self._fail_start(run, CaptureErrorCode.SOURCE_UNAVAILABLE, f"{type(exc).__name__}: {str(exc)[:200]}")
        if run.failure is None and not run.stop_requested:
            await self._save(run, lambda r: activate(r, now=self._clock()) if r.state is CaptureState.STARTING else r,
                             lambda r: (self._event(ActivityKind.CAPTURE_STARTED, r,
                                                    data={"channel": r.channel.value, "device": r.device,
                                                          "capture_source": r.source}),))
            # `source_start_ms` : temps jusqu'à la source prête (premier octet de l'encodeur d'écran),
            # à comparer à l'échéance de démarrage.
            self._trace("core.capture.started", "Capture démarrée",
                        data={**self._ids(run.record), "source_start_ms": int((time.perf_counter() - begun) * 1000)})
            for listener in self._started_listeners:
                self._spawn(self._notify(listener, run.record), f"capture-started-{run.record.capture_id}")

    async def _notify(self, listener: Callable[[CaptureRecord], Awaitable[None]], record: CaptureRecord) -> None:
        try:
            await listener(record)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: a listener never stops a recording; logged with its type
            self._trace("core.capture.listener_failed", f"{type(exc).__name__}: {str(exc)[:200]}", level="error",
                        data={**self._ids(record), "exception_type": type(exc).__name__})

    async def _fail_start(self, run: _Run, code: CaptureErrorCode, reason: str) -> None:
        """Échec du démarrage : capture et Artifact finis, puis `CaptureError` levée (ne rend jamais)."""

        if run.failure is None:
            run.failure = (code, reason)
        run.stop_requested = True
        await self._conclude(run, StopReason.START_FAILED)
        raise CaptureError(run.failure[0], f"capture {run.record.capture_id} did not start: {run.failure[1]}",
                           capture_id=run.record.capture_id)

    async def _abandon(self, run: _Run, exc: BaseException) -> None:
        """Échec hors règle (base refusée...) : on tente de finir proprement ; sinon la capture reste
        ouverte et visible (`stuck`), et son arrêt se rejoue au prochain `stop`/`start`/fermeture."""

        self._trace("core.capture.start_failed", f"Démarrage de capture en échec : {type(exc).__name__}: "
                    f"{str(exc)[:200]}", level="error",
                    data={**self._ids(run.record), "code": failure_code(exc).value,
                          "exception_type": type(exc).__name__})
        if run.failure is None:
            run.failure = (failure_code(exc), f"{type(exc).__name__}")
        run.stop_requested = True
        run.stop_reason = run.stop_reason or StopReason.START_FAILED
        try:
            await self._conclude(run, StopReason.START_FAILED)
        except asyncio.CancelledError:
            raise
        except Exception as again:  # noqa: BLE001 - capture: kept visible as stuck, stop replayed later
            self._mark_stuck(run, again)

    # ------------------------------------------------------------ capture ponctuelle

    async def screenshot(self, options: CaptureOptions | None = None,
                         channel: CaptureChannel | str = CaptureChannel.SCREEN) -> CaptureRecord:
        """Capture ponctuelle par le même propriétaire : ligne `captures` (mode `one_shot`), Artifact
        `screenshot` écrit atomiquement. Jamais en conflit avec un enregistrement d'écran. Pas
        d'événement `capture.*` : `artifact.created`/`artifact.finalized` disent le fait."""

        options = options or CaptureOptions()
        channel = self._channel(channel)
        self._refuse_when_closing()
        try:
            source = self._sources.one_shot(channel, source=options.source, device=options.device)
            source_name = self._sources.source_name(channel, CaptureMode.ONE_SHOT, options.source)
            kind = artifact_kind_of(channel, CaptureMode.ONE_SHOT)
        except CaptureError as exc:
            self._refused(channel, exc)
            raise
        association = await self._associate()
        record = new_capture(channel=channel, mode=CaptureMode.ONE_SHOT, source=source_name, device=options.device,
                             now=self._clock(), jarvis_session_id=association.jarvis_session_id,
                             context_id=association.context_id, data=options.data)
        try:
            await self._repo.insert_capture(record)
        except CaptureError:
            raise
        except Exception as exc:  # noqa: BLE001 - base refused: stable code, cause kept in the message
            raise CaptureError(failure_code(exc), f"capture store refused the screenshot: {type(exc).__name__}: "
                               f"{str(exc)[:200]}") from exc
        run = _Run(record=record)
        self._runs[record.capture_id] = run
        try:
            return await self._one_shot(run, source, kind)
        finally:
            self._forget(run)

    async def _one_shot(self, run: _Run, source: OneShotSource, kind: Any) -> CaptureRecord:
        """Une prise. Toute issue finit la ligne et l'Artifact (`complete` ou `failed`) avec un code stable ;
        une base qui refuse même cela laisse la ligne ouverte, journalisée, reprise au prochain démarrage."""

        record = run.record
        try:
            try:
                artifact = await self._artifacts.create(
                    kind=kind, source=f"capture.{record.channel.value}", jarvis_session_id=record.jarvis_session_id,
                    context_id=record.context_id, payload_name=source.payload_name, started_at=record.created_at,
                    mime_type=source.mime_type, metadata={"capture_id": record.capture_id, "device": record.device,
                                                          "capture_source": record.source},
                    capture_id=record.capture_id)
            except Exception as exc:  # noqa: BLE001 - registry refused: no artifact, the row fails with its code
                raise CaptureSourceError(failure_code(exc),
                                         f"artifact refused: {type(exc).__name__}: {str(exc)[:200]}") from exc
            run.artifact = artifact
            await self._save(run, lambda r: attach_artifact(r, artifact.artifact_id, now=self._clock()))
            try:
                result = await asyncio.wait_for(source.capture(), self._start_timeout_s)
            except TimeoutError:
                raise CaptureSourceError(CaptureErrorCode.SOURCE_TIMEOUT,
                                         f"no image within {self._start_timeout_s:g} s") from None
            except (CaptureSourceError, asyncio.CancelledError):
                raise
            except Exception as exc:  # noqa: BLE001 - said with its type, the screenshot fails with a stable code
                raise CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE,
                                         f"{type(exc).__name__}: {str(exc)[:200]}") from exc
            if result.details:
                await self._record_details(run, result.details)
            # `stopping` avant l'écriture : un arrêt brutal entre l'Artifact complet et
            # la ligne se réconcilie en `complete` (seul `stopping` peut y mener).
            await self._save(run, lambda r: request_stop(r, now=self._clock(), reason=StopReason.ONE_SHOT))
            try:
                done = await self._artifacts.store_payload(artifact.artifact_id, result.data, ended_at=self._clock(),
                                                           width=result.width, height=result.height)
            except ArtifactPayloadError as exc:
                raise CaptureSourceError(storage_code(exc, CaptureErrorCode.WRITE_FAILED),
                                         f"{exc.code}: {str(exc)[:200]}") from exc
            await self._save(run, lambda r: finish(r, now=self._clock(), state=CaptureState.COMPLETE,
                                                   bytes_written=done.size_bytes or 0))
        except CaptureSourceError as exc:
            code, reason = exc.code, str(exc)[:200]
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - base/registry refused mid-way: stable code, cause in reason
            code, reason = failure_code(exc), f"{type(exc).__name__}: {str(exc)[:200]}"
        else:
            self._trace("core.capture.screenshot", "Capture d'écran prise",
                        data={**self._ids(run.record), "size_bytes": done.size_bytes})
            return run.record
        await self._fail_one_shot(run, code)
        self._trace("core.capture.screenshot_failed", f"Capture d'écran en échec : {reason}", level="warning",
                    data={**self._ids(run.record), "code": code.value})
        raise CaptureError(code, f"screenshot {record.capture_id} failed: {reason}", capture_id=record.capture_id)

    async def _fail_one_shot(self, run: _Run, code: CaptureErrorCode) -> None:
        """Artifact puis ligne `failed` ; un refus ici est journalisé (la reprise du démarrage fermera)."""

        try:
            if run.artifact is not None:
                try:
                    await self._artifacts.fail(run.artifact.artifact_id, error_code=code.value)
                except ArtifactError as exc:
                    if exc.code is not ArtifactErrorCode.ARTIFACT_NOT_PENDING:
                        raise
            if run.record.is_open:
                await self._save(run, lambda r: finish(r, now=self._clock(), state=CaptureState.FAILED,
                                                       error_code=code.value, reason=StopReason.START_FAILED))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: logged, the row is reconciled at next start
            self._trace("core.capture.left_open", f"Capture d'écran laissée ouverte : {type(exc).__name__}: "
                        f"{str(exc)[:200]}", level="error",
                        data={**self._ids(run.record), "code": failure_code(exc).value})

    # ------------------------------------------------------------ arrêt

    async def stop(self, capture_id: str) -> CaptureRecord:
        """Arrêt idempotent : rend l'état final. Deux appels concurrents attendent le même arrêt ;
        une capture déjà finie est rendue telle quelle ; inconnue : `capture_not_found`."""

        check_capture_id(capture_id)
        run = self._runs.get(capture_id)
        if run is None or run.record.mode is CaptureMode.ONE_SHOT:
            return await self.get(capture_id)
        return await self._request_stop(run, StopReason.USER)

    async def _request_stop(self, run: _Run, reason: StopReason) -> CaptureRecord:
        """Arrêt à vol unique. Un arrêt bloqué (base refusée) lève `CaptureError` (`storage_unavailable`,
        `storage_full`...) et laisse la capture ouverte et visible ; l'appel suivant le rejoue."""

        run.stop_requested = True
        run.stop_reason = run.stop_reason or reason
        if run.stop_task is None:
            run.stop_task = asyncio.create_task(self._stop_flow(run, run.stop_reason),
                                                name=f"capture-stop-{run.record.capture_id}")
            self._track(run.stop_task)
        await asyncio.shield(run.stop_task)
        return run.record

    async def _stop_flow(self, run: _Run, reason: StopReason) -> None:
        try:
            # `stopping` écrit tout de suite : le statut le dit pendant que la source s'arrête.
            # Refusé ici : `_conclude` le réécrit sous le verrou (et arrête la source quoi qu'il arrive).
            if run.record.is_open:
                try:
                    await self._save(run, lambda r: request_stop(r, now=self._clock(), reason=reason))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - capture: logged, retried under the lifecycle lock
                    self._trace("core.capture.stopping_refused", f"`stopping` non écrit : {type(exc).__name__}",
                                level="warning", data={**self._ids(run.record), "code": failure_code(exc).value})
            async with run.lifecycle:
                if run.record.is_terminal or run.record.capture_id not in self._runs:
                    return
                await self._conclude(run, reason)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: kept visible as stuck, raised with a stable code
            stuck = self._mark_stuck(run, exc)
            run.stop_task = None  # le prochain appel rejoue l'arrêt
            raise CaptureError(stuck.error_code, f"capture {run.record.capture_id} could not be stopped: "
                               f"{stuck.reason}", capture_id=run.record.capture_id) from exc
        run.stuck = None

    def _mark_stuck(self, run: _Run, exc: BaseException) -> StuckCapture:
        """La capture reste en mémoire, ouverte, et garde son appareil : visible dans `status()`."""

        stuck = StuckCapture(run.record.capture_id, failure_code(exc), f"{type(exc).__name__}: {str(exc)[:200]}")
        run.stuck = stuck
        if run.record.capture_id not in self._runs:
            self._runs[run.record.capture_id] = run
        if run.record.mode is CaptureMode.CONTINUOUS:
            self._holders.setdefault(run.record.device_key, run.record.capture_id)
        self._trace("core.capture.stop_stuck", f"Arrêt de capture bloqué : {stuck.reason}", level="error",
                    data={**self._ids(run.record), "code": stuck.error_code.value,
                          "exception_type": type(exc).__name__})
        return stuck

    async def close(self) -> None:
        """Arrêt ordonné de Core : refuse tout démarrage, arrête chaque capture (`core_shutdown`).

        Une capture arrêtée ainsi finit comme un arrêt normal (`complete` si
        le payload est final et sans trou) ; son `capture.stopped` dit la raison.
        """

        self._closing = True
        runs = [run for run in self._runs.values() if run.record.mode is CaptureMode.CONTINUOUS]
        results = await asyncio.gather(*(self._request_stop(run, StopReason.CORE_SHUTDOWN) for run in runs),
                                       return_exceptions=True)
        for run, result in zip(runs, results):
            if isinstance(result, BaseException):
                self._trace("core.capture.close_failed", f"Capture non arrêtée proprement : {type(result).__name__}",
                            level="error", data=self._ids(run.record))
                # Ligne laissée ouverte (réconciliée au prochain démarrage) : `_halt_source` a déjà
                # arrêté la source et poussé sur disque ce qui restait dans le tampon.
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ------------------------------------------------------------ fin commune

    async def _conclude(self, run: _Run, reason: StopReason) -> None:
        """Arrête la source, finalise payload et Artifact, puis la ligne + `capture.stopped`. Verrou tenu.

        Rejouable : une base qui refuse en chemin lève, la capture reste en
        mémoire (ouverte, appareil tenu) et l'appel suivant reprend où elle en
        était — source déjà arrêtée, payload déjà finalisé (`run.payload`),
        Artifact déjà fini (`artifact_not_pending` toléré).
        """

        if run.record.is_open:
            try:
                await self._save(run, lambda r: request_stop(r, now=self._clock(), reason=reason))
            except BaseException:
                # Arrêt demandé : l'appareil s'arrête même si la base refuse (rien de ce qui est
                # écrit n'est perdu ; payload et ligne sont finis au rejeu ou à la reprise).
                await self._halt_source(run)
                raise
        await self._halt_source(run)
        await self._finish(run)

    async def _halt_source(self, run: _Run) -> None:
        """Source arrêtée (une seule fois), faits de fin gardés, cadence de durabilité arrêtée."""

        if run.source_started and run.source is not None:
            try:
                await asyncio.wait_for(run.source.stop(), self._stop_timeout_s)
            except TimeoutError:
                self._note_failure(run, CaptureErrorCode.SOURCE_TIMEOUT,
                                   f"source did not stop within {self._stop_timeout_s:g} s")
            except CaptureSourceError as exc:
                self._note_failure(run, exc.code, str(exc)[:200])
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - said with its type; the evidence is still finalized
                self._note_failure(run, CaptureErrorCode.SOURCE_LOST, f"{type(exc).__name__}: {str(exc)[:200]}")
            run.source_started = False
            try:
                run.media = run.source.media_info()
            except Exception as exc:  # noqa: BLE001 - optional facts: logged, the payload stays measured
                self._trace("core.capture.media_info_failed", f"Durée inconnue : {type(exc).__name__}",
                            level="warning", data=self._ids(run.record))
        await self._stop_durability(run)
        # Derniers octets sur disque tout de suite : un arrêt bloqué (base refusée) ne finalise le
        # payload qu'au rejeu ; une mort de Core d'ici là ne perd rien de ce que la source a écrit.
        # Dans un fil : il attend le `checkpoint` éventuellement encore en vol (verrou du sink).
        if run.sink is not None and run.payload is None:
            try:
                self._note_sync_refusal(run, await asyncio.to_thread(run.sink.checkpoint, durable=True))
            except CaptureSourceError:
                pass  # intentional: sink fermé ou disque refusé — la perte est déjà remise à `_on_failure`
            except Exception as exc:  # noqa: BLE001 - unexpected: said; the stop goes on, finalize decides
                self._note_failure(run, CaptureErrorCode.WRITE_FAILED, f"checkpoint: {type(exc).__name__}: "
                                   f"{str(exc)[:200]}")

    async def _finish(self, run: _Run) -> None:
        """Payload, Artifact, puis ligne terminale + `capture.stopped` (une transaction)."""

        if run.pending:
            await asyncio.gather(*list(run.pending), return_exceptions=True)
        state, error = await self._finalize_evidence(run, run.media)
        now = self._clock()
        bytes_written = run.sink.bytes_written if run.sink is not None else 0
        await self._save(
            run,
            lambda r: finish(r, now=now, state=state, error_code=None if error is None else error.value,
                             bytes_written=bytes_written, gaps=run.gaps),
            lambda r: (self._event(ActivityKind.CAPTURE_STOPPED, r, data={
                "state": r.state.value, "reason": r.stop_reason.value if r.stop_reason else None,
                "error_code": r.error_code, "gaps": r.gaps, "bytes_written": r.bytes_written,
                "channel": r.channel.value}),))
        self._forget(run)
        self._trace("core.capture.stopped", "Capture terminée",
                    level="info" if state is CaptureState.COMPLETE else "warning",
                    data={**self._ids(run.record), "state": state.value,
                          "error_code": run.record.error_code, "reason": run.record.stop_reason.value
                          if run.record.stop_reason else None, "gaps": run.gaps, "bytes_written": bytes_written})
        if not self._closing:
            for listener in self._stopped_listeners:
                self._spawn(self._notify(listener, run.record), f"capture-stopped-{run.record.capture_id}")

    async def _finalize_evidence(self, run: _Run, media: MediaInfo) -> tuple[CaptureState, CaptureErrorCode | None]:
        """Payload puis Artifact. `complete` seulement : payload final, aucune erreur, aucun trou."""

        if run.payload is None:
            run.payload = await self._finalize_payload(run)
        finalized, error = run.payload
        if run.artifact is not None and media.details:
            await self._record_details(run, media.details)
        if finalized and error is None and run.gaps == 0:
            state = CaptureState.COMPLETE
        elif finalized:
            state = CaptureState.PARTIAL
            error = error or CaptureErrorCode.CAPTURE_GAP
        else:
            state = CaptureState.FAILED
            error = error or CaptureErrorCode.FINALIZE_FAILED
        if run.artifact is not None:
            try:
                if state is CaptureState.FAILED:
                    await self._artifacts.fail(run.artifact.artifact_id, error_code=error.value, ended_at=self._clock())
                else:
                    await self._artifacts.finalize(
                        run.artifact.artifact_id, state=ArtifactState(state.value), ended_at=self._clock(),
                        duration_ms=media.duration_ms, width=media.width, height=media.height,
                        error_code=None if error is None else error.value)
            except ArtifactError as exc:
                if exc.code is not ArtifactErrorCode.ARTIFACT_NOT_PENDING:
                    raise
        return state, error

    async def _finalize_payload(self, run: _Run) -> tuple[bool, CaptureErrorCode | None]:
        """`fsync` + renommage du spool (ou fermeture s'il n'y a rien) : une seule fois par capture.

        Dans un fil : un disque lent (`fsync`, verrou du sink tenu par un `checkpoint` en vol)
        ne retient jamais la boucle de Core.
        """

        error = None if run.failure is None else run.failure[0]
        sink = run.sink
        if sink is None:
            return False, error
        try:
            if sink.bytes_accepted == 0 and error is not None:
                await asyncio.to_thread(sink.close)  # rien à promouvoir : un `.partial` vide reste
                return False, error
            await asyncio.to_thread(sink.finalize)
            return True, error
        except ArtifactPayloadError as exc:
            code = storage_code(exc, CaptureErrorCode.FINALIZE_FAILED)
            self._trace("core.capture.finalize_failed", f"Payload non finalisé : {str(exc)[:300]}",
                        level="error", data={**self._ids(run.record), "code": code.value, "payload_code": exc.code})
            return False, error or code

    async def _record_details(self, run: _Run, details: Mapping[str, Any]) -> None:
        """Faits d'acquisition de la source (format, appareil, écran, trous) dans les métadonnées de
        l'Artifact, avant sa finalisation. Refus (bornes, base) : journalisé, la preuve est finalisée
        quand même."""

        assert run.artifact is not None
        try:
            await self._artifacts.update_pending(run.artifact.artifact_id, metadata=dict(details))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - optional facts: logged with their cause, evidence still finalized
            self._trace("core.capture.media_details_refused", f"{type(exc).__name__}: {str(exc)[:200]}",
                        level="warning", data={**self._ids(run.record), "code": str(getattr(exc, "code", ""))})

    # ------------------------------------------------------------ durabilité (boucle de Core)

    async def _durability(self, run: _Run) -> None:
        """Toutes les `flush_interval_s` : spool remis au système ; `fsync` toutes les `fsync_interval_s`.

        Le disque est touché dans un fil (`fsync` peut prendre des millisecondes) ;
        la boucle s'arrête avec la source (`_stop_durability`), quand le sink est
        fermé ou en échec, ou quand la capture a quitté la mémoire.
        """

        sink = run.sink
        assert sink is not None
        last_sync = time.monotonic()
        while True:
            await asyncio.sleep(self._flush_interval_s)
            if self._runs.get(run.record.capture_id) is not run:
                return
            durable = time.monotonic() - last_sync >= self._fsync_interval_s
            try:
                self._note_sync_refusal(run, await asyncio.to_thread(sink.checkpoint, durable=durable))
            except CaptureSourceError:
                return  # sink fermé ou disque refusé : la perte est déjà remise au propriétaire (`_on_failure`)
            except Exception as exc:  # noqa: BLE001 - unexpected: said, and the capture stops like a storage loss
                self._on_failure(run, CaptureErrorCode.WRITE_FAILED, f"checkpoint: {type(exc).__name__}: "
                                 f"{str(exc)[:200]}")
                return
            if durable:
                last_sync = time.monotonic()

    def _note_sync_refusal(self, run: _Run, refusal: str | None) -> None:
        """`fsync` du fichier de l'encodeur refusé : non fatal (l'encodeur remet déjà chaque paquet au
        système), journalisé une fois par capture ; la perte sur coupure n'est alors plus bornée."""

        if refusal is None or run.sync_refused:
            return
        run.sync_refused = True
        self._trace("core.capture.encoder_sync_refused", f"`fsync` de l'encodeur refusé : {refusal[:200]}",
                    level="warning", data=self._ids(run.record))

    @staticmethod
    async def _stop_durability(run: _Run) -> None:
        task, run.durability = run.durability, None
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    # ------------------------------------------------------------ pertes et trous (boucle de Core)

    def _note_failure(self, run: _Run, code: CaptureErrorCode, reason: str) -> None:
        if run.failure is None:
            run.failure = (code, reason)
            self._trace("core.capture.failure", f"Capture en échec : {reason[:200]}", level="warning",
                        data={**self._ids(run.record), "code": code.value})

    def _on_failure(self, run: _Run, code: CaptureErrorCode, reason: str) -> None:
        """Perte de source ou stockage refusé : la capture s'arrête (arrêt à vol unique)."""

        first = run.failure is None
        self._note_failure(run, code, reason)
        if first and code is CaptureErrorCode.SOURCE_LOST:
            self._gap_event(run, "source_lost", None)
        if run.record.is_terminal or run.stop_requested:
            return
        run.stop_requested = True
        stop_reason = StopReason.SOURCE_LOST if code is CaptureErrorCode.SOURCE_LOST else StopReason.STORAGE_FAILURE
        self._spawn(self._request_stop(run, stop_reason), f"capture-autostop-{run.record.capture_id}")

    def _on_gap(self, run: _Run, reason: str, lost_ms: int | None) -> None:
        if run.record.is_terminal:
            return
        run.gaps += 1
        self._gap_event(run, reason, lost_ms)

    def _gap_event(self, run: _Run, reason: str, lost_ms: int | None) -> None:
        record = run.record
        self._trace("core.capture.gap", "Trou dans une capture", level="warning",
                    data={**self._ids(record), "reason": reason, "lost_ms": lost_ms})
        if record.jarvis_session_id is None:
            return
        task = self._spawn(self._artifacts.record(
            ActivityKind.CAPTURE_GAP, jarvis_session_id=record.jarvis_session_id, context_id=record.context_id,
            artifact_ids=() if record.artifact_id is None else (record.artifact_id,),
            capture_ids=(record.capture_id,), data={"reason": reason, "lost_ms": lost_ms,
                                                    "channel": record.channel.value}),
            f"capture-gap-{record.capture_id}")
        run.pending.add(task)
        task.add_done_callback(run.pending.discard)

    # ------------------------------------------------------------ Session et Context

    async def association_changed(self, reason: str) -> None:
        """La Session ou le Context actif a changé (rappel de `SessionManager`).

        Chaque capture continue ouverte **continue** et garde son association
        de démarrage ; un `capture.association_changed` est écrit dans la
        Session/Context nouvellement actifs, pour qu'une lecture de ce Context
        sache qu'une capture en cours le traverse. Ne lève pas.
        """

        runs = [run for run in self._runs.values()
                if run.record.mode is CaptureMode.CONTINUOUS and run.record.is_open]
        if not runs:
            return
        try:
            current = await self._associate()
        except CaptureError as exc:
            self._trace("core.capture.association_unreadable", str(exc)[:200], level="warning",
                        data={"code": exc.code.value, "reason": reason})
            return
        for run in runs:
            record = run.record
            if (record.jarvis_session_id, record.context_id) == (current.jarvis_session_id, current.context_id):
                continue
            try:
                await self._artifacts.record(
                    ActivityKind.CAPTURE_ASSOCIATION_CHANGED, jarvis_session_id=current.jarvis_session_id,
                    context_id=current.context_id, capture_ids=(record.capture_id,),
                    artifact_ids=() if record.artifact_id is None else (record.artifact_id,),
                    data={"reason": str(reason)[:64], "started_session_id": record.jarvis_session_id,
                          "started_context_id": record.context_id, "channel": record.channel.value})
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - capture: logged with its code, the recording goes on
                self._trace("core.capture.association_note_failed", f"{type(exc).__name__}: {str(exc)[:200]}",
                            level="error", data={**self._ids(record), "code": str(getattr(exc, "code", ""))})
                continue
            self._trace("core.capture.association_changed", "Capture en cours : Context actif changé",
                        data={**self._ids(record), "now_session_id": current.jarvis_session_id,
                              "now_context_id": current.context_id, "reason": reason})

    # ------------------------------------------------------------ reprise

    async def recover(self) -> CaptureRecoveryReport:
        """Au démarrage de Core, **avant** `ArtifactService.recover_pending` et tout écrivain.

        Toute capture ouverte appartient à une vie précédente (Core mort avec
        tout l'arbre du superviseur) : réparation de sa famille, reprise de son
        Artifact, `capture.gap` + `capture.stopped` (`recovered`) dans la
        transaction de sa fin. Jamais relancée. Ne lève pas (sauf annulation).
        """

        partial: list[str] = []
        failed: list[str] = []
        complete: list[str] = []
        repair_failed: list[str] = []
        unreadable: list[str] = []
        seen: set[str] = set()
        while True:
            try:
                # Les lignes laissées ouvertes (illisibles) sont les premières de l'ordre : on les saute.
                ids = [i for i in await self._repo.open_capture_ids(limit=RECOVERY_BATCH, offset=len(unreadable))
                       if i not in seen]
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - capture: said with its code, Core keeps starting
                self._trace("core.capture.recovery_failed", f"Réconciliation des captures interrompue : "
                            f"{type(exc).__name__}: {str(exc)[:200]}", level="error",
                            data={"code": str(getattr(exc, "code", "capture_store_failed")),
                                  "exception_type": type(exc).__name__})
                break
            if not ids:
                break
            for capture_id in ids:
                seen.add(capture_id)
                try:
                    record = await self._repo.get_capture(capture_id)
                    if record is None or not record.is_open:
                        continue
                    state, repair_ok = await self._recover_one(record)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - one bad row never blocks the others; logged, left open
                    unreadable.append(capture_id)
                    self._trace("core.capture.recover_one_failed", f"Capture non réconciliée : "
                                f"{type(exc).__name__}: {str(exc)[:200]}", level="error",
                                data={"capture_id": capture_id,
                                      "code": str(getattr(exc, "code", "capture_store_failed")),
                                      "exception_type": type(exc).__name__})
                    continue
                {CaptureState.PARTIAL: partial, CaptureState.FAILED: failed,
                 CaptureState.COMPLETE: complete}[state].append(capture_id)
                if not repair_ok:
                    repair_failed.append(capture_id)
        report = CaptureRecoveryReport(tuple(partial), tuple(failed), tuple(complete), tuple(repair_failed),
                                       tuple(unreadable))
        self._recovery = report
        self._trace("core.capture.recovery", "Réconciliation des captures d'une vie précédente",
                    level="error" if unreadable else "warning" if partial or failed or complete else "info",
                    data={"partial": len(partial), "failed": len(failed), "complete": len(complete),
                          "repair_failed": len(repair_failed), "unreadable": len(unreadable)})
        return report

    async def _recover_one(self, record: CaptureRecord) -> tuple[CaptureState, bool]:
        artifact: Artifact | None = None
        if record.artifact_id is not None:
            try:
                artifact = await self._artifacts.get(record.artifact_id)
            except ArtifactError as exc:
                if exc.code is not ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                    raise
        repair_ok = True
        repair_detail = None
        recovered_now = False
        # Dernière écriture connue : date du payload sur disque (avant toute réparation), sinon la ligne.
        last_seen, last_seen_source = record.updated_at, "capture_row"
        written = None if artifact is None else self._last_payload_write(artifact)
        if written is not None:
            last_seen, last_seen_source = written, "payload_write"
        if artifact is not None and artifact.is_pending:
            outcome, repair_ok = await self._repair(record, artifact)
            repair_detail = None if outcome is None else outcome.detail
            if outcome is not None and not outcome.usable:
                # La famille sait le payload illisible (conteneur vidéo sans fragment
                # complet) : `failed`, jamais un `partial` qu'aucun lecteur n'ouvre.
                artifact = await self._artifacts.fail(artifact.artifact_id,
                                                      error_code=CaptureErrorCode.CAPTURE_INTERRUPTED.value)
            else:
                artifact = await self._artifacts.recover(
                    artifact.artifact_id, duration_ms=None if outcome is None else outcome.duration_ms)
            recovered_now = True
        if artifact is None:
            state, code = CaptureState.FAILED, CaptureErrorCode.CAPTURE_INTERRUPTED.value
        elif artifact.is_pending:
            # Payload refusé (jonction, dossier illisible...) : l'Artifact reste `pending` exprès —
            # le finir `failed` jetterait une preuve qui redevient lisible quand le dossier est
            # réparé ; `recover_pending` le réessaie à chaque démarrage. La capture, elle, se ferme
            # (l'appareil se libère) et dit `recoverable_partial`.
            state, code = CaptureState.PARTIAL, CaptureErrorCode.RECOVERABLE_PARTIAL.value
        elif artifact.state is ArtifactState.COMPLETE:
            state = CaptureState.COMPLETE if record.state is CaptureState.STOPPING else CaptureState.PARTIAL
            code = None if state is CaptureState.COMPLETE else CaptureErrorCode.RECOVERABLE_PARTIAL.value
        elif artifact.state is ArtifactState.PARTIAL:
            state = CaptureState.PARTIAL
            code = (CaptureErrorCode.RECOVERABLE_PARTIAL.value if recovered_now
                    else artifact.error_code or CaptureErrorCode.RECOVERABLE_PARTIAL.value)
        else:
            state = CaptureState.FAILED
            code = (CaptureErrorCode.CAPTURE_INTERRUPTED.value if recovered_now
                    else artifact.error_code or CaptureErrorCode.CAPTURE_INTERRUPTED.value)
        now = max(self._clock(), record.updated_at)
        data: dict[str, Any] = {"recovered_from": record.state.value}
        if repair_detail:
            data["repair"] = repair_detail[:200]
        if not repair_ok:
            data["repair_failed"] = True
        updated = finish(record, now=now, state=state, error_code=code, reason=StopReason.RECOVERED,
                         bytes_written=0 if artifact is None else artifact.size_bytes or 0, data=data)
        activity: tuple[ActivityDraft, ...] = ()
        if record.jarvis_session_id is not None and record.mode is CaptureMode.CONTINUOUS:
            gap = self._event(ActivityKind.CAPTURE_GAP, updated, data={
                "reason": "core_restart", "last_seen_at": last_seen.isoformat(), "last_seen_source": last_seen_source,
                "recovered_from": record.state.value, "channel": record.channel.value})
            stopped = self._event(ActivityKind.CAPTURE_STOPPED, updated, data={
                "state": state.value, "reason": StopReason.RECOVERED.value, "error_code": code,
                "gaps": updated.gaps, "bytes_written": updated.bytes_written, "channel": record.channel.value})
            activity = (gap, stopped) if state is not CaptureState.COMPLETE else (stopped,)
        await self._repo.update_capture(record, updated, activity=activity)
        self._trace("core.capture.recovered", "Capture d'une vie précédente réconciliée", level="warning",
                    data={**self._ids(updated), "state": state.value, "error_code": code,
                          "recovered_from": record.state.value, "repair_failed": not repair_ok})
        return state, repair_ok

    def _last_payload_write(self, artifact: Artifact) -> datetime | None:
        """Date de dernière écriture du payload (`.partial`, sinon final) ; `None` si inconnue.

        Le propriétaire remet le spool au système chaque seconde : c'est la
        dernière écriture qui a survécu à la mort de Core, sans aucun coût en vie.
        """

        try:
            files = self._artifacts.payload_files(artifact)
        except ArtifactPayloadError:
            return None
        if files is None:
            return None
        for path in (files.partial_path, files.final_path):
            try:
                return datetime.fromtimestamp(os.stat(path).st_mtime, tz=timezone.utc)
            except OSError:
                continue
        return None

    async def _repair(self, record: CaptureRecord, artifact: Artifact) -> tuple[RepairOutcome | None, bool]:
        repair = self._repairs.get(record.channel)
        if repair is None:
            return None, True
        try:
            files = self._artifacts.payload_files(artifact)
            if files is None:
                return None, True
            target = RepairTarget(capture=record, artifact_id=artifact.artifact_id, partial_path=files.partial_path,
                                  final_path=files.final_path, partial_bytes=files.info.partial_bytes,
                                  final_bytes=files.info.final_bytes)
            return await asyncio.wait_for(_in_daemon_thread(repair.repair, target), self._repair_timeout_s), True
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            # Le fil bloqué n'est pas tuable ; démon, il ne retient pas la sortie de Core. Le payload
            # est repris tel quel (s'il est encore ouvert par le fil, sa promotion échoue : l'Artifact
            # reste `pending`, réessayé au prochain démarrage).
            self._trace("core.capture.repair_timeout", f"Réparation sans réponse après {self._repair_timeout_s:g} s",
                        level="error", data={**self._ids(record), "code": "capture_repair_timeout"})
            return None, False
        except Exception as exc:  # noqa: BLE001 - capture: logged, the evidence is recovered as it is
            self._trace("core.capture.repair_failed", f"Réparation impossible : {type(exc).__name__}: "
                        f"{str(exc)[:200]}", level="error",
                        data={**self._ids(record), "code": str(getattr(exc, "code", "capture_repair_failed")),
                              "exception_type": type(exc).__name__})
            return None, False

    # ------------------------------------------------------------ interne

    @staticmethod
    def _channel(channel: CaptureChannel | str) -> CaptureChannel:
        try:
            return CaptureChannel(channel)
        except ValueError:
            raise CaptureError(CaptureErrorCode.UNSUPPORTED_SOURCE, f"unknown capture channel {str(channel)[:40]!r}") \
                from None

    def _refuse_when_closing(self) -> None:
        if self._closing:
            raise CaptureError(CaptureErrorCode.SERVICE_STOPPING, "Core is stopping: no capture can start")

    async def _associate(self) -> CaptureAssociation:
        try:
            return await self._association()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise CaptureError(CaptureErrorCode.ASSOCIATION_UNAVAILABLE,
                               f"active session/context unreadable: {type(exc).__name__}: {str(exc)[:200]}") from exc

    async def _save(self, run: _Run, change: Callable[[CaptureRecord], CaptureRecord],
                    activity: Callable[[CaptureRecord], tuple[ActivityDraft, ...]] | None = None) -> CaptureRecord:
        """Transition appliquée à l'état **courant** (sûre entre démarrage et arrêt concurrents)."""

        async with run.write:
            previous = run.record
            updated = change(previous)
            if updated == previous:
                return previous
            drafts = () if activity is None or updated.jarvis_session_id is None else activity(updated)
            await self._repo.update_capture(previous, updated, activity=drafts)
            run.record = updated
            return updated

    @staticmethod
    def _event(kind: ActivityKind, record: CaptureRecord, *, data: Mapping[str, Any]) -> ActivityDraft:
        return ActivityDraft(kind=kind, occurred_at=record.updated_at, jarvis_session_id=record.jarvis_session_id,
                             context_id=record.context_id, capture_ids=(record.capture_id,),
                             artifact_ids=() if record.artifact_id is None else (record.artifact_id,), data=data)

    async def _stop_source_quietly(self, run: _Run) -> None:
        if run.source is None:
            return
        try:
            await asyncio.wait_for(run.source.stop(), self._stop_timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: logged; the start already failed with its own code
            self._trace("core.capture.source_stop_failed", f"{type(exc).__name__}: {str(exc)[:200]}",
                        level="warning", data=self._ids(run.record))

    def _forget(self, run: _Run) -> None:
        if run.durability is not None and not run.durability.done():
            run.durability.cancel()
        record = run.record
        if self._runs.get(record.capture_id) is run:
            del self._runs[record.capture_id]
        if self._holders.get(record.device_key) == record.capture_id:
            del self._holders[record.device_key]

    def _spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro, name=name)
        self._track(task)
        return task

    def _track(self, task: asyncio.Task[Any]) -> None:
        self._tasks.add(task)

        def done(finished: asyncio.Task[Any]) -> None:
            self._tasks.discard(finished)
            if finished.cancelled():
                return
            exc = finished.exception()
            if exc is not None and not isinstance(exc, CaptureError):
                self._trace("core.capture.task_failed", f"{finished.get_name()} : {type(exc).__name__}: "
                            f"{str(exc)[:200]}", level="error",
                            data={"task": finished.get_name()[:80], "exception_type": type(exc).__name__})

        task.add_done_callback(done)

    def _refused(self, channel: CaptureChannel, exc: CaptureError) -> None:
        self._trace("core.capture.refused", str(exc)[:200], level="warning",
                    data={"channel": channel.value, "code": exc.code.value, "capture_id": exc.capture_id})

    @staticmethod
    def _ids(record: CaptureRecord) -> dict[str, Any]:
        return {"capture_id": record.capture_id, "channel": record.channel.value, "mode": record.mode.value,
                "artifact_id": record.artifact_id, "jarvis_session_id": record.jarvis_session_id,
                "context_id": record.context_id}

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not stop a capture
            pass
