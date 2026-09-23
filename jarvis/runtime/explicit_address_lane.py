"""La lane d'adresse explicite : mot d'éveil et touche manuelle, un seul type.

D05 : « le mot d'éveil et la touche manuelle sont la même chose ». D04 : « le
déclencheur doit être admis sans attendre le moindre travail ambiant ». Cette
lane est l'endroit où les deux décisions deviennent du code.

Ce qu'elle est, structurellement
--------------------------------

Un **fan-in borné**, sur le motif déjà en place dans ce dépôt
(`CompositeWakeWordBackend`, `asyncio.Queue(maxsize=4)`) — avec la seule chose
que ce motif perd et que D05 exige : **la source**. Un `str` « jarvis » ne dit
pas s'il vient du micro ou du clavier ; un `ExplicitAddressTrigger` le dit, et
porte en plus le temps **monotone** de son admission.

Pourquoi elle implémente aussi `WakeWordBackend`
------------------------------------------------

`PersistentVoiceRuntime.run()` consomme `wakeword.detections()` et rend des
chaînes. Réécrire ce chemin serait toucher à SIMPLE, que D14 interdit. La lane
est donc un **remplaçant direct** de `CompositeWakeWordBackend` : `detections()`
rend l'étiquette, `triggers()` rend le type complet, et ce sont **deux vues de
la même file**, pas deux files — un déclencheur sort par l'une ou par l'autre,
jamais par les deux. La Slice 10 basculera le chemin adressé sur `triggers()` ;
d'ici là, rien de ce qui existe ne change de forme.

Indépendance du travail ambiant
-------------------------------

La lane ne connaît rien de l'ambiant : aucune référence, aucun `await` sur quoi
que ce soit qui en dépende. Un pompage par source, une file bornée, une
estampille prise au moment de l'admission. Un abonné ambiant saturé ne peut pas
retarder un appui, et `test_presentation_audio_capture.py` le prouve en mesurant
la latence sous saturation délibérée.

Isolation des pannes
--------------------

Une source qui lève emporte **sa** tâche de pompage, pas les autres. Le refus
est dit à `error` et reste lisible dans `source_failures` ; la lane continue de
servir les sources qui tiennent. C'est la règle de `docs/03-implementation-strategy.md`
— une panne du détecteur laisse la touche manuelle utilisable — et c'est
exactement ce que l'ancien `CompositeWakeWordBackend._pump` ne garantissait pas,
puisqu'une exception y remontait dans une tâche que personne n'attend.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable

from jarvis.domain.explicit_address import (
    MAX_TRIGGER_AGE_S,
    ExplicitAddressSource,
    ExplicitAddressTrigger,
)

#: Profondeur de la file de déclencheurs. Même valeur que
#: `CompositeWakeWordBackend` — c'est le motif de fan-in borné de la maison. Un
#: humain n'appuie pas quatre fois d'avance ; au-delà, ce ne serait plus une
#: file mais une mémoire d'appuis périmés.
DEFAULT_LANE_QUEUE_SIZE = 4


class ExplicitAddressLane:
    """Fan-in typé et borné des sources d'adresse explicite."""

    def __init__(
        self,
        *,
        journal: object | None = None,
        maxsize: int = DEFAULT_LANE_QUEUE_SIZE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.journal = journal
        self.clock = clock
        self._queue: asyncio.Queue[ExplicitAddressTrigger] = asyncio.Queue(maxsize=max(1, int(maxsize)))
        self._sources: list[tuple[ExplicitAddressSource, object]] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._closed = False
        self._sequence = 0
        #: Comptabilité observable, pour que chaque garantie de l'en-tête soit
        #: constatable depuis un test plutôt que crue sur parole.
        self.admitted = 0
        self.dropped = 0
        self.delivered = 0
        self.stale_deliveries = 0
        self.last_admission: ExplicitAddressTrigger | None = None
        self.last_delivery_latency_s: float | None = None
        self.source_failures: dict[str, str] = {}

    # -- traces -----------------------------------------------------------

    def _trace(self, kind: str, message: str, *, level: str = "info", **data: object) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=dict(data))

    # -- composition ------------------------------------------------------

    def add_source(self, source: ExplicitAddressSource, backend: object) -> None:
        """Brancher une source. À faire avant `start()`."""

        if not isinstance(source, ExplicitAddressSource):
            raise TypeError("source must be an ExplicitAddressSource")
        self._sources.append((source, backend))

    @property
    def sources(self) -> tuple[ExplicitAddressSource, ...]:
        return tuple(source for source, _ in self._sources)

    @property
    def live_sources(self) -> tuple[ExplicitAddressSource, ...]:
        """Les sources qui n'ont pas échoué. Vide = plus personne n'adresse JARVIS."""

        return tuple(source for source in self.sources if source.value not in self.source_failures)

    async def start(self) -> None:
        if self._closed or self._tasks:
            return
        if not self._sources:
            raise ValueError("at least one explicit-address source is required")
        self._tasks = [
            asyncio.create_task(self._pump(source, backend), name=f"jarvis-explicit-address-{source.value}")
            for source, backend in self._sources
        ]
        self._trace(
            "explicit_address.started", "Lane d'adresse explicite ouverte",
            sources=[source.value for source, _ in self._sources],
        )

    async def _pump(self, source: ExplicitAddressSource, backend: object) -> None:
        """Une tâche par source. Son échec ne concerne qu'elle."""

        try:
            async for label in backend.detections():  # type: ignore[attr-defined]
                if self._closed:
                    return
                self._admit(source, label)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.source_failures[source.value] = type(exc).__name__
            self._trace(
                "explicit_address.source_failed",
                f"Source d'adresse « {source.label} » hors service : {type(exc).__name__}: {exc}. "
                f"Sources encore vivantes : {[s.value for s in self.live_sources] or 'aucune'}.",
                level="error", code="explicit_address_source_failed", source=source.value,
                live_sources=[s.value for s in self.live_sources],
            )

    # -- admission --------------------------------------------------------

    def _admit(self, source: ExplicitAddressSource, label: object) -> ExplicitAddressTrigger | None:
        """Estampiller et déposer. Synchrone et non bloquant, par construction :
        rien de ce qui se passe ailleurs ne peut retarder cette ligne."""

        text = str(label or "").strip().lower()[:32] or source.value
        try:
            trigger = ExplicitAddressTrigger.admitted(
                source, text, sequence=self._sequence, clock=self.clock,
            )
        except Exception as exc:
            # Une étiquette hors contrat vient d'un backend, pas de l'utilisateur :
            # on le dit et on n'admet rien plutôt que d'inventer un déclencheur.
            self._trace(
                "explicit_address.label_refused",
                f"Déclencheur refusé pour « {source.label} » : {type(exc).__name__}: {exc}",
                level="error", code="explicit_address_label_refused", source=source.value,
            )
            return None
        self._sequence += 1
        if self._queue.full():
            # Contre-pression : on écarte le **plus ancien**. Un appui en
            # attente derrière trois autres ne désigne plus la phrase en cours.
            try:
                stale = self._queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - full() vient d'être vrai
                stale = None
            self.dropped += 1
            self._trace(
                "explicit_address.dropped",
                "Déclencheur le plus ancien écarté : la lane est pleine",
                level="warning", code="explicit_address_dropped",
                dropped=self.dropped,
                discarded=stale.to_payload() if stale is not None else None,
            )
        self._queue.put_nowait(trigger)
        self.admitted += 1
        self.last_admission = trigger
        self._trace(
            "explicit_address.admitted", f"Adresse explicite par {source.label}",
            **trigger.to_payload(),
        )
        return trigger

    # -- consommation -----------------------------------------------------

    async def triggers(self) -> AsyncIterator[ExplicitAddressTrigger]:
        """La vue typée. Vue **jumelle** de `detections()`, pas seconde file."""

        await self.start()
        while not self._closed:
            trigger = await self._queue.get()
            self.delivered += 1
            now = self.clock()
            self.last_delivery_latency_s = trigger.age_s(now)
            if not trigger.is_fresh(now):
                # Jamais écarté : perdre un appui de l'utilisateur est pire que
                # d'en servir un vieux. Mais un déclencheur périmé se dit, et le
                # consommateur dispose de `is_fresh` pour en décider.
                self.stale_deliveries += 1
                self._trace(
                    "explicit_address.stale",
                    f"Déclencheur servi avec {round(self.last_delivery_latency_s, 3)} s de retard "
                    f"(seuil {MAX_TRIGGER_AGE_S} s)",
                    level="warning", code="explicit_address_stale",
                    latency_s=round(self.last_delivery_latency_s, 3), **trigger.to_payload(),
                )
            yield trigger

    async def detections(self) -> AsyncIterator[str]:
        """La vue chaîne, pour `PersistentVoiceRuntime` tel qu'il est aujourd'hui."""

        async for trigger in self.triggers():
            yield trigger.label

    # -- contrat WakeWordBackend ------------------------------------------

    async def suspend(self) -> None:
        for _, backend in self._sources:
            await backend.suspend()  # type: ignore[attr-defined]
        self._clear_pending()

    async def suspend_for_active_session(self) -> None:
        """Déléguer, sans réinterpréter.

        `KeyboardWakeWordBackend.suspend_for_active_session()` garde
        délibérément la touche armée pour qu'un second appui soumette le tour.
        La lane ne doit surtout pas l'écraser : elle transmet, exactement comme
        `CompositeWakeWordBackend`.
        """

        for _, backend in self._sources:
            await backend.suspend_for_active_session()  # type: ignore[attr-defined]
        self._clear_pending()

    async def resume(self) -> None:
        for _, backend in self._sources:
            await backend.resume()  # type: ignore[attr-defined]

    def _clear_pending(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - empty() vient d'être vrai
                break

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for _, backend in self._sources:
            await backend.close()  # type: ignore[attr-defined]
        self._trace(
            "explicit_address.closed", "Lane d'adresse explicite fermée",
            admitted=self.admitted, delivered=self.delivered, dropped=self.dropped,
            stale=self.stale_deliveries,
        )

    def stats(self) -> dict[str, object]:
        return {
            "sources": [source.value for source in self.sources],
            "live_sources": [source.value for source in self.live_sources],
            "source_failures": dict(self.source_failures),
            "admitted": self.admitted,
            "delivered": self.delivered,
            "dropped": self.dropped,
            "stale_deliveries": self.stale_deliveries,
            "pending": self._queue.qsize(),
            "last_admission": self.last_admission.to_payload() if self.last_admission is not None else None,
            "last_delivery_latency_s": (
                None if self.last_delivery_latency_s is None
                else round(self.last_delivery_latency_s, 6)
            ),
        }
