"""Service Core de la scène constellation (handoff jarvis-constellation-scene-runtime, Slice 02).

Core possède la scène (Décision 11) : même processus que la vérité de
travail. `SceneService` implémente `SceneCommandSink` et `SceneReader` :

1. les commandes sont sérialisées par un verrou asyncio et pliées par
   `apply_scene_command` (le domaine décide : autorité, bornes, révision) ;
2. une commande appliquée est **persistée d'abord**, en une transaction
   (`SceneRepository.commit`) ;
3. seulement ensuite la scène en mémoire avance, le patch entre dans un anneau
   borné (`PATCH_RING_SIZE`) et les attentes de `wait_for_revision` sont
   réveillées.

La scène ne passe **pas** par `CoreEventBus` : `/v1/events` relaie chaque
événement du bus, sans filtre, à tous ses clients WebSocket, Voice compris. Des
patchs de scène y pèseraient jusqu'à plusieurs mégaoctets, et une rafale de la
projection pourrait remplir la file bornée d'un abonné et l'évincer. Personne
n'écoute la scène par diffusion : le transport (Slice 03) attend localement
une révision (`wait_for_revision`) puis lit `patches_since`.

Échec d'écriture : la révision n'avance pas, rien n'entre dans l'anneau, aucune
attente n'est réveillée ; l'échec est journalisé (`core.scene.persist_failed`)
et l'appelant reçoit `ScenePersistenceError`. Si le stockage a divergé de la
mémoire (`revision_conflict`), la scène devient indisponible jusqu'au
prochain démarrage : servir une mémoire que le disque contredit mentirait au
redémarrage suivant.

Démarrage : `start()` ouvre le fichier, charge la scène ou en crée une avec
un `scene_id` stable. Un fichier plus récent, inconnu ou corrompu est un
refus explicite et journalisé (`core.scene.unavailable`) : la scène reste
indisponible, le reste de Core démarre, et le fichier n'est jamais effacé.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
import math

from jarvis.core.v2_services import NullDiagnosticSink
from jarvis.domain.scene import (
    SceneCommand,
    SceneCommandOutcome,
    ScenePatch,
    SceneSnapshot,
    SceneUpdate,
    apply_scene_command,
)
from jarvis.ports.scene import (
    ArchivedSceneObject,
    ScenePatchWindow,
    ScenePersistenceError,
    SceneRepository,
    SceneStoreError,
    SceneStoreErrorCode,
    SceneUnavailableError,
)
from jarvis.ports.v2 import DiagnosticSink

SCENE_LOADED_KIND = "core.scene.loaded"
SCENE_UNAVAILABLE_KIND = "core.scene.unavailable"
SCENE_PERSIST_FAILED_KIND = "core.scene.persist_failed"
SCENE_COMMAND_REFUSED_KIND = "core.scene.command_refused"
SCENE_CLOSE_FAILED_KIND = "core.scene.close_failed"
SCENE_SWEPT_KIND = "core.scene.swept"
SCENE_SWEEP_FAILED_KIND = "core.scene.sweep_failed"

#: Patchs gardés en mémoire pour le transport. Au-delà, un consommateur en
#: retard reçoit `resync_required` et relit l'instantané.
PATCH_RING_SIZE = 512
#: Borne d'une attente de révision (long-poll du transport, Slice 03).
MAX_REVISION_WAIT_S = 30.0
_MAX_REPORTED = 256


def _consume_outcome(task: asyncio.Future[SceneUpdate]) -> None:
    if not task.cancelled():
        task.exception()


class SceneState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    #: Refus au démarrage ou stockage divergé : rien n'est servi.
    UNAVAILABLE = "unavailable"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class SceneAvailability:
    state: SceneState
    code: SceneStoreErrorCode | None = None
    detail: str = ""


class SceneService:
    """Scène active possédée par Core. Implémente `SceneCommandSink` et `SceneReader`."""

    def __init__(
        self,
        repository: SceneRepository,
        *,
        diagnostics: DiagnosticSink | None = None,
        patch_ring_size: int = PATCH_RING_SIZE,
    ) -> None:
        if not 1 <= patch_ring_size <= PATCH_RING_SIZE:
            raise ValueError(f"patch_ring_size must be between 1 and {PATCH_RING_SIZE}")
        self._repository = repository
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._lock = asyncio.Lock()
        self._snapshot: SceneSnapshot | None = None
        self._ring: deque[ScenePatch] = deque(maxlen=patch_ring_size)
        self._availability = SceneAvailability(SceneState.STARTING)
        self._reported: set[tuple[str, ...]] = set()
        #: Remplacé à chaque changement (révision commise, fermeture,
        #: divergence) : l'ancien est levé, ses attentes se réveillent et
        #: relisent l'état ; les suivantes attendent le nouveau.
        self._changed = asyncio.Event()

    @property
    def availability(self) -> SceneAvailability:
        return self._availability

    # ------------------------------------------------------------ cycle de vie

    async def start(self) -> SceneAvailability:
        """Charger ou créer la scène. Ne lève pas : un refus rend la scène indisponible.

        Toute exception est capturée ici, et pas seulement `SceneStoreError` :
        la scène est une projection, un défaut de son stockage ne doit jamais
        empêcher Core de démarrer. Le type et le message réels sont journalisés.
        """

        async with self._lock:
            if self._availability.state is not SceneState.STARTING:
                return self._availability
            await self._sweep()
            try:
                created = await self._repository.initialize()
                snapshot = await self._repository.load()
            except Exception as exc:
                code = exc.code if isinstance(exc, SceneStoreError) else SceneStoreErrorCode.STORAGE_IO
                detail = f"{type(exc).__name__}: {exc}"
                self._availability = SceneAvailability(SceneState.UNAVAILABLE, code, detail)
                self._emit(
                    SCENE_UNAVAILABLE_KIND,
                    "scène refusée au démarrage : indisponible, fichier laissé intact, reste de Core en service",
                    level="error",
                    data={"code": code.value, "error": detail},
                )
                await self._close_repository()
                return self._availability
            self._snapshot = snapshot
            self._availability = SceneAvailability(SceneState.READY)
            self._emit(
                SCENE_LOADED_KIND,
                "scène créée" if created else "scène rechargée",
                data={
                    "scene_id": snapshot.scene_id,
                    "revision": snapshot.revision,
                    "objects": len(snapshot.objects),
                    "relations": len(snapshot.relations),
                    "archived_ids": len(snapshot.archived_ids),
                    "created": created,
                },
            )
            return self._availability

    async def _sweep(self) -> None:
        """Balayer les restes du stockage avant de l'ouvrir ; un échec n'empêche jamais le démarrage."""

        try:
            report = await self._repository.sweep_leftovers()
        except Exception as exc:
            self._emit(
                SCENE_SWEEP_FAILED_KIND,
                "balayage des restes de la scène impossible",
                level="warning",
                data={"error": f"{type(exc).__name__}: {exc}"},
            )
            return
        if report.removed:
            self._emit(
                SCENE_SWEPT_KIND,
                "temporaires de création interrompue de la scène retirés",
                data={"removed": list(report.removed)},
            )
        if report.failed:
            self._emit(
                SCENE_SWEEP_FAILED_KIND,
                "restes de la scène non retirés",
                level="warning",
                data={"failed": list(report.failed)},
            )

    async def close(self) -> None:
        async with self._lock:
            if self._availability.state is SceneState.CLOSED:
                return
            self._availability = SceneAvailability(SceneState.CLOSED, SceneStoreErrorCode.UNAVAILABLE, "scene closed")
            self._snapshot = None
            self._ring.clear()
            self._notify_change()
            await self._close_repository()

    async def _close_repository(self) -> None:
        try:
            await self._repository.close()
        except Exception as exc:
            # Fermeture pendant l'arrêt de Core : rien à relancer, mais la
            # cause reste lisible.
            self._emit(
                SCENE_CLOSE_FAILED_KIND,
                "fermeture du stockage de scène en échec",
                level="warning",
                data={"error": f"{type(exc).__name__}: {exc}"},
            )

    # ------------------------------------------------------------ commandes

    async def apply(self, command: SceneCommand) -> SceneUpdate:
        """Appliquer une commande ; rend le `SceneUpdate` du domaine.

        L'application se poursuit dans une tâche protégée : annuler l'appelant
        pendant l'écriture ne laisse jamais le disque en avance sur la mémoire
        (la commande se termine, réveille les attentes, et l'appelant reçoit
        `CancelledError`).
        """

        task = asyncio.ensure_future(self._apply_serialized(command))
        # Si l'appelant est annulé, l'issue de la tâche n'a plus de lecteur :
        # on la consomme (un échec est déjà journalisé par `_persistence_failed`).
        task.add_done_callback(_consume_outcome)
        return await asyncio.shield(task)

    async def _apply_serialized(self, command: SceneCommand) -> SceneUpdate:
        async with self._lock:
            current = self._require_snapshot()
            update = apply_scene_command(current, command)
            if update.outcome in (SceneCommandOutcome.REJECTED_AUTHORITY, SceneCommandOutcome.INVALID):
                self._report_refusal(command, update)
            if update.patch is None:
                return update
            try:
                await self._repository.commit(current, update.patch, update.snapshot)
            except Exception as exc:
                raise self._persistence_failed(current, update.patch, exc) from exc
            self._snapshot = update.snapshot
            self._ring.append(update.patch)
            self._notify_change()
            return update

    def _persistence_failed(self, current: SceneSnapshot, patch: ScenePatch, exc: Exception) -> ScenePersistenceError:
        """Journaliser l'échec d'écriture et construire l'erreur rendue à l'appelant."""

        code = exc.code if isinstance(exc, SceneStoreError) else SceneStoreErrorCode.STORAGE_IO
        detail = f"{type(exc).__name__}: {exc}"
        # Divergence ou stockage coincé : servir la mémoire mentirait au
        # prochain redémarrage, ou chaque commande suivante échouerait.
        diverged = (
            (isinstance(exc, SceneStoreError) and exc.fatal)
            or code in (SceneStoreErrorCode.REVISION_CONFLICT, SceneStoreErrorCode.UNAVAILABLE)
        )
        self._emit(
            SCENE_PERSIST_FAILED_KIND,
            "commande de scène non persistée : révision inchangée, aucune attente réveillée"
            + (" ; scène rendue indisponible" if diverged else ""),
            level="error",
            data={
                "scene_id": current.scene_id,
                "revision": current.revision,
                "attempted_revision": patch.revision,
                "code": code.value,
                "error": detail,
            },
        )
        if diverged:
            self._availability = SceneAvailability(SceneState.UNAVAILABLE, code, detail)
            self._snapshot = None
            self._ring.clear()
            self._notify_change()
        return ScenePersistenceError(code, f"scene revision {patch.revision} was not persisted: {detail}")

    def _notify_change(self) -> None:
        event, self._changed = self._changed, asyncio.Event()
        event.set()

    # ------------------------------------------------------------ lecture

    async def snapshot(self) -> SceneSnapshot:
        return self._require_snapshot()

    async def patches_since(self, revision: int, *, scene_id: str | None = None) -> ScenePatchWindow:
        """Patchs de révision > `revision`, ou `resync_required` si l'anneau ne couvre pas l'écart."""

        if isinstance(revision, bool) or not isinstance(revision, int):
            raise TypeError("revision must be an integer")
        current = self._require_snapshot()
        window = ScenePatchWindow(scene_id=current.scene_id, revision=current.revision, patches=(), resync_required=True)
        if (scene_id is not None and scene_id != current.scene_id) or not 0 <= revision <= current.revision:
            return window
        if revision == current.revision:
            return ScenePatchWindow(current.scene_id, current.revision, (), resync_required=False)
        if not self._ring or self._ring[0].revision > revision + 1:
            return window
        patches = tuple(patch for patch in self._ring if patch.revision > revision)
        return ScenePatchWindow(current.scene_id, current.revision, patches, resync_required=False)

    async def wait_for_revision(self, after: int, *, timeout_s: float) -> int:
        """Attendre une révision supérieure à `after` ; rendre la révision courante.

        Rend dès que la révision dépasse `after`, ou à l'échéance avec la
        révision inchangée. `timeout_s` est borné à [0, `MAX_REVISION_WAIT_S`].
        Scène indisponible ou fermée, à l'entrée comme pendant l'attente :
        `SceneUnavailableError`, sans attendre l'échéance. Annuler l'attente ne
        laisse rien derrière elle (aucune tâche, aucun abonnement).
        """

        if isinstance(after, bool) or not isinstance(after, int):
            raise TypeError("after must be an integer")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or math.isnan(timeout_s):
            raise TypeError("timeout_s must be a number")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + min(max(float(timeout_s), 0.0), MAX_REVISION_WAIT_S)
        while True:
            current = self._require_snapshot()
            remaining = deadline - loop.time()
            if current.revision > after or remaining <= 0:
                return current.revision
            try:
                async with asyncio.timeout(remaining):
                    await self._changed.wait()
            except TimeoutError:
                return self._require_snapshot().revision

    async def archived_history(self, *, object_id: str | None = None, limit: int = 100) -> tuple[ArchivedSceneObject, ...]:
        self._require_snapshot()
        return await self._repository.archived_history(object_id=object_id, limit=limit)

    def _require_snapshot(self) -> SceneSnapshot:
        if self._snapshot is None:
            availability = self._availability
            raise SceneUnavailableError(
                availability.code or SceneStoreErrorCode.UNAVAILABLE,
                f"scene is {availability.state.value}" + (f": {availability.detail}" if availability.detail else ""),
            )
        return self._snapshot

    # ------------------------------------------------------------ diagnostic

    def _report_refusal(self, command: SceneCommand, update: SceneUpdate) -> None:
        reason = update.reason.value if update.reason is not None else ""
        key = ("refused", command.actor.value, command.op.value, update.outcome.value, reason)
        if key in self._reported:
            return
        if len(self._reported) >= _MAX_REPORTED:
            self._reported.clear()
        self._reported.add(key)
        self._emit(
            SCENE_COMMAND_REFUSED_KIND,
            f"commande de scène refusée ({update.outcome.value}/{reason})",
            data={"actor": command.actor.value, "op": command.op.value, "outcome": update.outcome.value, "reason": reason},
        )

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict) -> None:
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            # Même règle que `CoreEventBus` et `WorkStateStore` : un journal
            # indisponible ne fait jamais échouer la scène.
            pass
