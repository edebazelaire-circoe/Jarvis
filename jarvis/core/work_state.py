"""Magasin Core de l'état de travail normalisé (handoff work-state, tâche 11).

Core est l'autorité sur le travail en cours : les observateurs de bord
(`AgentTaskTracker` dans le Control Center, `JobService` dans Core) remettent
des `WorkObservation` ; le magasin les ordonne avec `apply_observation`,
avance la révision globale, borne la rétention et publie `core.work.updated`
sur `CoreEventBus`. Le cerveau et l'UI lisent le même instantané par
`WorkStateReader.snapshot()`.

Durée de vie : en mémoire seulement, comme les liens de job de `JobService`.
Un redémarrage de Core repart d'un magasin vide, avec un nouveau `store_id`
et une révision à 0 ; les producteurs voient ce changement d'identifiant à
leur envoi suivant (au plus tard leur renvoi périodique au repos) et
renvoient leur état complet. Rien d'autre n'est rejoué : un travail qui
vivait dans Core (un job) est repris par `JobService.recover`, qui l'observe
`interrupted`. Un producteur qui disparaît sans revenir (Control Center tué)
laisse ses éléments actifs tels quels : ils sont interrompus quand une
nouvelle instance du producteur se présente (`producer_id` différent) — mais
seulement ceux que Core attribue à l'instance remplacée et dont ce premier
lot ne parle pas. Le revendicateur courant de la source peut ensuite rouvrir
un de ces éléments s'il le constate encore actif. Une reprise de main ne tue
donc jamais un travail qui tourne encore.

Attribution : Core retient, hors du fil et hors de tout instantané, le
producteur propriétaire de chaque élément et la liste des clés qu'il a
lui-même interrompues en revendiquant une source. Ces deux mémoires sont la
seule autorité pour rouvrir : aucun champ que le producteur écrit sur le fil
(`error_class` en particulier) n'en tient lieu.

Le bus ne porte que l'état public normalisé (`WorkItem.to_payload`) : jamais
de trace ni de JSON de fournisseur.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace

from jarvis.core.v2_services import CoreEventBus, NullDiagnosticSink, SystemClock
from jarvis.domain.v2 import ProtocolEnvelope, new_id
from jarvis.domain.work_state import (
    MAX_WORK_ITEMS,
    ObservationOutcome,
    WorkItem,
    WorkObservation,
    WorkObservationBatch,
    WorkSnapshot,
    WorkStatus,
    WorkUpdate,
    apply_observation,
)
from jarvis.ports.v2 import Clock, DiagnosticSink

#: Un élément créé ou modifié. Charge utile : `store_id`, `revision`,
#: `previous_status` (`None` à la création) et `item`. Une fin ou un échec se
#: lit dans `item.status` : pas d'événement distinct, pour ne pas doubler le
#: trafic d'un bus borné. Un changement d'état n'est pas une prise de parole.
CORE_WORK_UPDATED = "core.work.updated"

WORK_OBSERVATION_IGNORED_KIND = "core.work.observation_ignored"
WORK_OBSERVATION_CONFLICT_KIND = "core.work.observation_conflict"
WORK_PRODUCER_RESTARTED_KIND = "core.work.producer_restarted"
#: Une source suivie est sortie de la mémoire des revendications (`MAX_PRODUCERS`).
WORK_PRODUCER_FORGOTTEN_KIND = "core.work.producer_forgotten"

#: Issues propres au magasin, en plus de `ObservationOutcome`.
#: `capacity` : création refusée, le magasin est plein d'éléments actifs.
CAPACITY_OUTCOME = "capacity"
#: `evicted` : l'élément visé a été élagué après sa fin ; il ne renaît pas.
EVICTED_OUTCOME = "evicted"
#: `error_class` des éléments d'un producteur remplacé par une autre instance.
PRODUCER_RESTARTED = "producer_restarted"

#: Clés élaguées retenues : une observation tardive d'un travail terminé puis
#: élagué ne le fait pas réapparaître. Dimensionné au-dessus de tout ce qu'un
#: renvoi complet peut rejouer — au plus `MAX_PRODUCERS` (32) sources, chacune
#: rejouant au plus ce que Core accepterait d'elle (`MAX_WORK_ITEMS` = 64
#: actifs) plus la trentaine de terminés que garde son suivi : ~3 000 clés.
#: Au-delà de cette borne (des dizaines de milliers de travaux dans une même
#: vie de Core), la clé la plus ancienne est oubliée et un renvoi tardif
#: recréerait ce travail terminé comme neuf. Choix assumé : oublier borne la
#: mémoire, et l'issue `evicted` reste comptée dans `outcome_totals`.
MAX_EVICTED_KEYS = 4096
#: Producteurs retenus (un par source). Au-delà de cette borne, la
#: revendication la plus ancienne est oubliée, et la garantie de reprise
#: s'éteint pour cette source : la prochaine instance y lira « aucun
#: revendicateur connu », n'interrompra donc rien, et le travail de l'instance
#: remplacée restera `running` jusqu'au redémarrage de Core. C'est l'échec dans
#: le bon sens (rien n'est tué à tort), mais il ne doit pas être silencieux :
#: l'oubli est signalé une fois par source (`WORK_PRODUCER_FORGOTTEN_KIND`).
#: 32 sources distinctes dans une même vie de Core ne se produit pas sur un
#: poste de travail ; si cela se produit, l'opérateur doit pouvoir le lire.
MAX_PRODUCERS = 32
_MAX_REPORTED = 256
#: Issues normales, comptées mais jamais signalées au diagnostic : un doublon
#: ou un progrès en retard est le lot ordinaire d'un flux rejoué.
_SILENT_OUTCOMES = frozenset({ObservationOutcome.DUPLICATE.value, ObservationOutcome.STALE.value, EVICTED_OUTCOME})


def _reopened_after_producer_restart(current: WorkItem | None, observation: WorkObservation) -> WorkItem | None:
    """Base rouverte d'un élément que Core avait interrompu en revendiquant sa source.

    Seule exception à « un état terminal ne se rouvre pas », et elle est
    étroite : l'élément doit être `interrupted` et l'observation doit le dire
    encore actif. L'autorité, elle, est vérifiée par l'appelant
    (`WorkStateStore._may_reopen`) : c'est Core qui doit avoir posé cette
    interruption, et le producteur qui parle doit être le revendicateur
    courant de la source. Il constate alors que ce travail n'avait jamais été
    abandonné. Sans cette exception, l'élément resterait interrompu pour
    toujours et le cerveau verrait un travail mort qui tourne encore.

    `updated_at` est gardé tel quel : l'observation qui rouvre est jugée
    comme toute autre, donc un constat antérieur à l'interruption reste en
    retard (`STALE`) au lieu de rembobiner l'élément.
    """

    if current is None or observation.status.is_terminal:
        return None
    if current.status is not WorkStatus.INTERRUPTED:
        return None
    return replace(current, status=observation.status, error_class=None, ended_at=None)


@dataclass(frozen=True, slots=True)
class WorkIngestResult:
    """Accusé d'un lot : ce que Core en a fait, sans rien de ce qu'il contenait."""

    store_id: str
    revision: int
    outcomes: tuple[tuple[str, int], ...]
    interrupted: int = 0

    def to_payload(self) -> dict[str, object]:
        return {
            "store_id": self.store_id,
            "revision": self.revision,
            "outcomes": dict(self.outcomes),
            "interrupted": self.interrupted,
        }


class WorkStateStore:
    """État de travail détaillé, possédé par Core. Implémente
    `WorkObservationSink` et `WorkStateReader`.

    Tout s'exécute dans la boucle de Core : chaque application calcule sa
    révision et range l'élément sans rendre la main, puis publie. Deux
    observations concurrentes ne peuvent donc pas prendre la même révision.

    Rétention : au plus `max_items` éléments. Une création au-delà élague
    l'élément terminé le plus ancien ; un élément actif n'est jamais élagué, et
    si tous le sont, la création est refusée (`capacity`) et signalée. Un
    élagage ne publie rien : il accompagne une création, qui avance la
    révision.
    """

    def __init__(
        self,
        *,
        events: CoreEventBus | None = None,
        diagnostics: DiagnosticSink | None = None,
        clock: Clock | None = None,
        max_items: int = MAX_WORK_ITEMS,
    ) -> None:
        if not 1 <= max_items <= MAX_WORK_ITEMS:
            raise ValueError(f"max_items must be between 1 and {MAX_WORK_ITEMS}")
        #: Identité de cette instance : change à chaque démarrage de Core.
        self.store_id = new_id()
        self._events = events
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._clock: Clock = clock or SystemClock()
        self._max_items = max_items
        self._items: dict[tuple[str, str], WorkItem] = {}
        self._revision = 0
        self._updated_at = self._clock.now()
        self._evicted: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._producers: OrderedDict[str, str] = OrderedDict()
        #: Attribution privée à Core : producteur propriétaire de chaque
        #: élément, et clés que Core lui-même a interrompues en revendiquant
        #: une source. Bornées par `_items`, jamais publiées ni lisibles sur
        #: le fil : elles portent l'autorité, pas la donnée.
        self._owners: dict[tuple[str, str], str] = {}
        self._core_interrupted: set[tuple[str, str]] = set()
        self._outcome_totals: dict[str, int] = {}
        self._reported: set[tuple[str, ...]] = set()

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def outcome_totals(self) -> dict[str, int]:
        """Observations reçues depuis le démarrage, par issue."""

        return dict(self._outcome_totals)

    # ------------------------------------------------------------------ ports

    async def observe(self, observation: WorkObservation) -> None:
        await self.apply(observation)

    async def snapshot(self) -> WorkSnapshot:
        return self.current_snapshot()

    def current_snapshot(self) -> WorkSnapshot:
        """Actifs du plus ancien au plus récent, puis terminés du plus récent au plus ancien."""

        items = self._items.values()
        active = sorted((item for item in items if not item.status.is_terminal), key=lambda item: (item.started_at, item.revision))
        finished = sorted(
            (item for item in items if item.status.is_terminal),
            key=lambda item: (item.ended_at, item.revision),
            reverse=True,
        )
        return WorkSnapshot(revision=self._revision, items=(*active, *finished), updated_at=self._updated_at)

    # -------------------------------------------------------------- ingestion

    async def ingest(self, batch: WorkObservationBatch) -> WorkIngestResult:
        """Appliquer un lot venu d'un autre processus, dans l'ordre du lot.

        Le producteur n'est revendiqué qu'**après** le lot : une nouvelle
        instance n'interrompt que les travaux qui lui sont attribués et dont
        elle ne parle pas. Ce qu'elle constate dans ce même lot continue de
        tourner.
        """

        counts: dict[str, int] = {}
        for observation in batch.observations:
            outcome = await self.apply(observation, producer=batch.producer_id)
            counts[outcome] = counts.get(outcome, 0) + 1
        interrupted = await self._claim_producer(
            batch.source, batch.producer_id, reported={observation.external_id for observation in batch.observations}
        )
        return WorkIngestResult(
            store_id=self.store_id,
            revision=self._revision,
            outcomes=tuple(sorted(counts.items())),
            interrupted=interrupted,
        )

    async def apply(self, observation: WorkObservation, *, producer: str | None = None) -> str:
        """Appliquer une observation ; rend son issue (`ObservationOutcome` ou issue du magasin).

        `producer` est l'instance d'observateur qui parle, telle que
        l'ingress l'a lue sur le lot (`WorkObservationBatch.producer_id`) :
        elle attribue l'élément et sert à vérifier l'autorité de réouverture.
        Les observateurs internes de Core (`JobService`, `observe`) n'en ont
        pas et ne revendiquent donc jamais rien.
        """

        key = observation.key
        current = self._items.get(key)
        if current is None and key in self._evicted:
            return self._ignored(observation, EVICTED_OUTCOME)
        reopened = _reopened_after_producer_restart(current, observation) if self._may_reopen(key, producer) else None
        update = apply_observation(reopened or current, observation, revision=self._revision + 1)
        if reopened is not None and update.outcome is ObservationOutcome.DUPLICATE:
            # Rouvrir est en soi un changement, même si l'observation
            # n'apporte rien d'autre : sans cela l'élément resterait interrompu.
            update = WorkUpdate(
                ObservationOutcome.UPDATED,
                replace(reopened, revision=self._revision + 1, updated_at=max(reopened.updated_at, observation.observed_at)),
                update.conflicts,
            )
        if update.conflicts:
            self._report(
                ("conflict", *key, *update.conflicts),
                WORK_OBSERVATION_CONFLICT_KIND,
                "rattachement contradictoire ignoré : la première valeur affirmée fait foi",
                data={"source": key[0], "external_id": key[1], "fields": list(update.conflicts)},
            )
        if not update.changed:
            return self._ignored(observation, update.outcome.value)
        if current is None and not self._make_room():
            return self._ignored(observation, CAPACITY_OUTCOME, level="warning")
        self._revision = update.item.revision
        self._items[key] = update.item
        if producer is not None:
            self._owners[key] = producer
        if reopened is not None:
            # L'interruption posée par Core est révoquée : elle ne servira
            # plus d'autorisation à une réouverture ultérieure.
            self._core_interrupted.discard(key)
        self._updated_at = max(self._updated_at, self._clock.now())
        self._count(update.outcome.value)
        await self._publish(update.item, current.status if current is not None else None)
        return update.outcome.value

    async def interrupt_source(
        self, source: str, *, error_class: str, keep: frozenset[str] = frozenset(), owner: str | None = None
    ) -> int:
        """Interrompre les éléments actifs d'une source dont l'hôte a disparu.

        `keep` épargne les `external_id` dont l'hôte vient de parler : ceux-là
        n'ont pas été abandonnés. `owner` restreint aux éléments que Core
        attribue à ce producteur : une instance remplacée n'emporte jamais le
        travail d'une autre instance, ni celui d'un observateur interne.

        Une interruption posée ici avec `PRODUCER_RESTARTED` est retenue comme
        telle : c'est la seule qui autorisera plus tard une réouverture.
        """

        now = self._clock.now()
        targets = [
            item
            for item in self._items.values()
            if item.source == source
            and not item.status.is_terminal
            and item.external_id not in keep
            and (owner is None or self._owners.get(item.key) == owner)
        ]
        for item in targets:
            outcome = await self.apply(
                WorkObservation(
                    source=source,
                    external_id=item.external_id,
                    status=WorkStatus.INTERRUPTED,
                    observed_at=now,
                    error_class=error_class,
                )
            )
            if error_class == PRODUCER_RESTARTED and outcome == ObservationOutcome.UPDATED.value:
                self._core_interrupted.add(item.key)
        return len(targets)

    def _may_reopen(self, key: tuple[str, str], producer: str | None) -> bool:
        """Vrai si `producer` a autorité pour rouvrir `key`.

        Deux conditions, toutes deux tenues par Core : cette clé est l'une de
        celles que Core a interrompues en revendiquant la source, et le
        producteur qui parle est le revendicateur courant de cette source.
        Rien n'est déduit du contenu de l'observation : un producteur qui
        écrit lui-même `error_class=producer_restarted` ne rouvre rien.
        """

        return producer is not None and key in self._core_interrupted and self._producers.get(key[0]) == producer

    async def _claim_producer(self, source: str, producer_id: str, *, reported: set[str] | None = None) -> int:
        known = self._producers.get(source)
        if known == producer_id:
            return 0
        self._producers[source] = producer_id
        self._producers.move_to_end(source)
        while len(self._producers) > MAX_PRODUCERS:
            forgotten, _ = self._producers.popitem(last=False)
            # Oublier une revendication désarme la reprise de main sur cette
            # source : on le dit, plutôt que de perdre la garantie en silence.
            self._report(
                ("producer_forgotten", forgotten),
                WORK_PRODUCER_FORGOTTEN_KIND,
                "trop de sources suivies : une reprise de main sur cette source n'interrompra plus rien",
                level="warning",
                data={"source": forgotten, "max_producers": MAX_PRODUCERS},
            )
        if known is None:
            # Premier contact depuis le démarrage de Core : rien d'antérieur à
            # interrompre, le magasin est parti vide.
            return 0
        interrupted = await self.interrupt_source(
            source, error_class=PRODUCER_RESTARTED, keep=frozenset(reported or ()), owner=known
        )
        self._report(
            ("producer", source, producer_id),
            WORK_PRODUCER_RESTARTED_KIND,
            "nouvelle instance d'observateur : ses travaux encore actifs sont interrompus",
            data={"source": source, "interrupted": interrupted},
        )
        return interrupted

    # ------------------------------------------------------------- rétention

    def _make_room(self) -> bool:
        if len(self._items) < self._max_items:
            return True
        finished = [item for item in self._items.values() if item.status.is_terminal]
        if not finished:
            return False
        oldest = min(finished, key=lambda item: (item.ended_at, item.revision))
        del self._items[oldest.key]
        self._owners.pop(oldest.key, None)
        self._core_interrupted.discard(oldest.key)
        self._evicted[oldest.key] = None
        while len(self._evicted) > MAX_EVICTED_KEYS:
            self._evicted.popitem(last=False)
        return True

    # ----------------------------------------------------------- publication

    async def _publish(self, item: WorkItem, previous: WorkStatus | None) -> None:
        if self._events is None:
            return
        payload = {
            "store_id": self.store_id,
            "revision": item.revision,
            "previous_status": previous.value if previous is not None else None,
            "item": item.to_payload(),
        }
        if item.link.correlation_id is not None:
            envelope = ProtocolEnvelope(message_type=CORE_WORK_UPDATED, payload=payload, correlation_id=item.link.correlation_id)
        else:
            envelope = ProtocolEnvelope(message_type=CORE_WORK_UPDATED, payload=payload)
        await self._events.publish(envelope)

    # ------------------------------------------------------------ diagnostic

    def _count(self, outcome: str) -> None:
        self._outcome_totals[outcome] = self._outcome_totals.get(outcome, 0) + 1

    def _ignored(self, observation: WorkObservation, outcome: str, *, level: str = "info") -> str:
        self._count(outcome)
        if outcome not in _SILENT_OUTCOMES:
            self._report(
                ("ignored", *observation.key, outcome),
                WORK_OBSERVATION_IGNORED_KIND,
                f"observation de travail ignorée ({outcome})",
                level=level,
                data={
                    "source": observation.source,
                    "external_id": observation.external_id,
                    "status": observation.status.value,
                    "outcome": outcome,
                },
            )
        return outcome

    def _report(self, dedupe: tuple[str, ...], kind: str, message: str, *, level: str = "info", data: dict) -> None:
        """Signaler une anomalie une fois par clé, dans une mémoire bornée."""

        if dedupe in self._reported:
            return
        if len(self._reported) >= _MAX_REPORTED:
            self._reported.clear()
        self._reported.add(dedupe)
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            # Un journal indisponible ne doit jamais faire échouer l'ingestion.
            pass
