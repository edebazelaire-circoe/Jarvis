"""Registre des montages que l'hote rapporte (handoff jarvis-interactive-presentation-studio, Slice 06).

Le navigateur monte les cadres ; Core ne le voit pas. Pour qu'un rechargement a chaud sache si la nouvelle source a
**vraiment** monte (et non seulement qu'elle a ete publiee), la page rapporte ce que l'hote a observe pour chaque cadre
`presentation-studio.*` : `mounted` (pret, stable) ou `failed` (raison courte + message du cadre). Ce registre fait le
lien entre un rechargement qui attend (`expect`) et le rapport qui arrive (`report`) :

- on s'inscrit **avant** de patcher le stage (un rapport rapide ne se perd pas) ;
- on attend avec une echeance (`MountWaiter.wait`) : sans rapport, `None`, jamais une attente sans fin ;
- un rapport sans attente (tardif, ou le montage d'une scene jamais affichee) est rendu a l'appelant, qui decide
  (`PresentationStudioReloadService.handle_mount_report`).
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass

from jarvis.domain.presentation_studio_reload import MountReport


class MountWaiter:
    """Une attente de rapport pour `(object_id, pin)`. `wait` rend le rapport ou `None` a l'echeance."""

    def __init__(self, book: MountBook, key: tuple[str, str, int], meta: dict | None = None) -> None:
        self._book, self._key = book, key
        #: Ce que l'attente sait de la scene (`scene_id`, `source_revision`) : rendu avec le rapport qui la resout.
        self.meta: dict = dict(meta or {})
        self._future: asyncio.Future[MountReport] = asyncio.get_running_loop().create_future()

    async def wait(self, timeout_s: float) -> MountReport | None:
        try:
            return await asyncio.wait_for(asyncio.shield(self._future), timeout_s)
        except TimeoutError:
            return None
        finally:
            self.cancel()

    def deliver(self, report: MountReport) -> None:
        if not self._future.done():
            self._future.set_result(report)

    def cancel(self) -> None:
        self._book._forget(self._key, self)
        if not self._future.done():
            self._future.cancel()


@dataclass(frozen=True, slots=True)
class MountStats:
    reports: int
    delivered: int
    unmatched: int
    waiting: int


class MountBook:
    def __init__(self, *, ring: int = 64) -> None:
        self._waiters: dict[tuple[str, str, int], list[MountWaiter]] = {}
        self._recent: deque[MountReport] = deque(maxlen=ring)
        self._reports = self._delivered = self._unmatched = 0

    def expect(self, object_id: str, prefab_id: str, version: int, meta: dict | None = None) -> MountWaiter:
        key = (object_id, prefab_id, version)
        waiter = MountWaiter(self, key, meta)
        self._waiters.setdefault(key, []).append(waiter)
        return waiter

    def report(self, report: MountReport) -> list[dict]:
        """Remet le rapport aux attentes de ce cadre et de ce pin ; rend leurs `meta` (liste vide : personne n'attendait)."""

        self._reports += 1
        self._recent.append(report)
        waiters = self._waiters.pop((report.object_id, report.prefab.prefab_id, report.prefab.version), [])
        for waiter in waiters:
            waiter.deliver(report)
        self._delivered += len(waiters)
        if not waiters:
            self._unmatched += 1
        return [waiter.meta for waiter in waiters]

    def _forget(self, key: tuple[str, str, int], waiter: MountWaiter) -> None:
        waiters = self._waiters.get(key)
        if waiters is None:
            return
        if waiter in waiters:
            waiters.remove(waiter)
        if not waiters:
            self._waiters.pop(key, None)

    def stats(self) -> MountStats:
        return MountStats(self._reports, self._delivered, self._unmatched,
                          sum(len(items) for items in self._waiters.values()))
