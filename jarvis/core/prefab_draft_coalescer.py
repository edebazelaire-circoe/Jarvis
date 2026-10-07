"""Brouillons coalescés : une rafale de retouches de source publie UNE version (handoff
jarvis-interactive-presentation-studio, Slice 01a).

`PrefabService.save` publie une version immuable par appel. Une répétition de retouches parlées ou le rechargement
à chaud du Studio (Slice 06) en enverrait des dizaines à la suite ; ce module les regroupe **avant** la
bibliothèque, il n'y ajoute aucune règle :

- `submit(candidate, actor=, derived_from=)` garde le **dernier** candidat par id ; la publication part après
  `quiet_s` de silence, ou au plus tard `max_wait_s` après la première retouche de la rafale (une retouche continue
  ne reste jamais sans publication) ;
- tous les appels de la rafale attendent **la même** publication (ou la même erreur typée de `PrefabService.save`) ;
- un changement d'acteur ou de `derived_from` au sein d'une rafale publie d'abord ce qui est en attente : on ne
  fusionne jamais deux intentions de provenance différente ;
- `flush()` publie tout de suite (fin de répétition, arrêt de Core) ; annuler un appelant n'annule pas la publication ;
- une rafale n'est jamais perdue en silence : l'erreur de `save` revient à chaque appelant, et le nombre de
  retouches fusionnées est tracé (`core.prefab.draft_coalesced`).

Un candidat invalide n'est pas retenu : il est confié tout de suite à `save`, qui le refuse avec ses erreurs typées.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from jarvis.core.prefab_service import PrefabService
from jarvis.domain.prefab import CreatorActor, PrefabRef, Publication, is_prefab_id
from jarvis.ports.v2 import DiagnosticSink

DEFAULT_QUIET_SECONDS = 2.0
DEFAULT_MAX_WAIT_SECONDS = 10.0


@dataclass(slots=True, eq=False)
class _Burst:
    candidate: object
    actor: CreatorActor | str
    derived_from: PrefabRef | None
    started: float
    merged: int = 1
    waiters: list[asyncio.Future[Publication]] = field(default_factory=list)
    timer: asyncio.Task[None] | None = None


class PrefabDraftCoalescer:
    """Voir l'en-tête du module. Une instance par `PrefabService` ; à utiliser dans la boucle d'événements de Core."""

    def __init__(self, service: PrefabService, *, quiet_s: float = DEFAULT_QUIET_SECONDS,
                 max_wait_s: float = DEFAULT_MAX_WAIT_SECONDS, diagnostics: DiagnosticSink | None = None) -> None:
        if not 0 < quiet_s <= max_wait_s:
            raise ValueError("quiet_s must be > 0 and at most max_wait_s")
        self._service = service
        self._quiet_s = quiet_s
        self._max_wait_s = max_wait_s
        self._diagnostics = diagnostics
        self._bursts: dict[str, _Burst] = {}
        self._inflight: set[_Burst] = set()
        self._tasks: set[asyncio.Future[None]] = set()

    @property
    def pending_ids(self) -> tuple[str, ...]:
        return tuple(self._bursts)

    async def submit(self, candidate: object, *, actor: CreatorActor | str,
                     derived_from: PrefabRef | None = None) -> Publication:
        prefab_id = self._id_of(candidate)
        if prefab_id is None:
            return await self._service.save(candidate, actor=actor, derived_from=derived_from)  # typed refusal
        loop = asyncio.get_running_loop()
        burst = self._bursts.get(prefab_id)
        if burst is not None and (burst.actor, burst.derived_from) != (actor, derived_from):
            await self._flush_one(prefab_id)
            burst = None
        waiter: asyncio.Future[Publication] = loop.create_future()
        # A caller cancelled mid-wait never reads the outcome: mark it retrieved so it is not reported as lost.
        waiter.add_done_callback(lambda done: done.cancelled() or done.exception())
        if burst is None:
            burst = self._bursts[prefab_id] = _Burst(candidate, actor, derived_from, loop.time())
        else:
            burst.candidate, burst.merged = candidate, burst.merged + 1
            if burst.timer is not None:
                burst.timer.cancel()
        burst.waiters.append(waiter)
        delay = min(self._quiet_s, max(0.0, burst.started + self._max_wait_s - loop.time()))
        burst.timer = loop.create_task(self._fire_after(prefab_id, burst, delay))
        return await asyncio.shield(waiter)

    async def flush(self, prefab_id: str | None = None) -> None:
        """Publie tout de suite la rafale de `prefab_id` (toutes si `None`) et rend quand c'est fait."""

        for pending in [prefab_id] if prefab_id is not None else list(self._bursts):
            if pending in self._bursts:
                await self._flush_one(pending)
        # Publications already started by a timer: wait for them too (their outcome goes to their own callers).
        waiting = [w for burst in list(self._inflight) for w in burst.waiters]
        if waiting:
            await asyncio.gather(*waiting, return_exceptions=True)

    @staticmethod
    def _id_of(candidate: object) -> str | None:
        manifest = candidate.get("manifest") if isinstance(candidate, Mapping) else None
        prefab_id = manifest.get("id") if isinstance(manifest, Mapping) else None
        return prefab_id if is_prefab_id(prefab_id) else None

    async def _fire_after(self, prefab_id: str, burst: _Burst, delay: float) -> None:
        await asyncio.sleep(delay)
        if self._bursts.get(prefab_id) is burst:
            await self._publish_detached(prefab_id, burst)

    async def _flush_one(self, prefab_id: str) -> None:
        burst = self._bursts.get(prefab_id)
        if burst is None:
            return
        if burst.timer is not None and burst.timer is not asyncio.current_task():
            burst.timer.cancel()
        await self._publish_detached(prefab_id, burst)

    async def _publish_detached(self, prefab_id: str, burst: _Burst) -> None:
        """Publie dans sa propre tâche, protégée : annuler l'appelant (ou la minuterie, à la fermeture de la boucle)
        n'annule ni la publication ni le brouillon d'un autre appelant ; son issue va à ses propres attentes."""

        task = asyncio.ensure_future(self._publish(prefab_id, burst))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        await asyncio.shield(task)

    async def _publish(self, prefab_id: str, burst: _Burst) -> None:
        if self._bursts.get(prefab_id) is not burst:
            return  # published already (flush racing the timer)
        del self._bursts[prefab_id]
        self._inflight.add(burst)
        try:
            publication = await self._service.save(burst.candidate, actor=burst.actor, derived_from=burst.derived_from)
        except BaseException as exc:  # noqa: BLE001 - intentional: handed to every waiter below, never swallowed
            for waiter in burst.waiters:
                if not waiter.done():
                    waiter.set_exception(exc if isinstance(exc, Exception) else RuntimeError(repr(exc)))
            if not isinstance(exc, Exception):
                raise
            return
        finally:
            self._inflight.discard(burst)
        self._trace(prefab_id, publication, burst)
        for waiter in burst.waiters:
            if not waiter.done():
                waiter.set_result(publication)

    def _trace(self, prefab_id: str, publication: Publication, burst: _Burst) -> None:
        if self._diagnostics is None:
            return
        data: dict[str, Any] = {"prefab_id": prefab_id, "version": publication.version, "merged": burst.merged}
        try:
            self._diagnostics.emit("core.prefab.draft_coalesced", "Retouches de source regroupées en une version",
                                   level="info", data=data)
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a publication
            pass
