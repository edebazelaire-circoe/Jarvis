"""La voie de préparation spéculative de Presentation. Bornée, sacrificielle, muette.

Slice 08. Le producteur est la voie ambiante (Slice 06), qui remet des
`AmbientTrigger` ; la sortie est l'ensemble de travail de la Slice 04, plus des
objets de scène **masqués**. Entre les deux, ce service admet, déduplique,
plafonne, exécute, normalise et range — et ne dit jamais rien à voix haute.

## Pourquoi une voie à part, et non `BackBrainTaskService`

`SLICE.md` demande un audit de fraîcheur avant de fabriquer quoi que ce soit.
Il a été fait, et il conclut à la réutilisation du **vocabulaire** et au refus
du **chemin d'exécution**. Deux faits mesurés, tous deux vérifiables :

1. `back_brain` a déjà un `scope="speculative_analysis"` — mais son profil
   d'exécution lance le CLI avec `--tools ""`
   (`jarvis/runtime/claude_local.py`, `restricted_args`). **Zéro outil.** C'est
   exactement ce qu'il faut pour relire une transcription, et exactement ce
   qu'il ne faut pas pour D07, qui demande recherche, résolution de document,
   inspection de code et veille web. Élargir ce profil-là élargirait aussi le
   chemin adressé qui le partage ;
2. `OwnedJobExecution._slots` est un `asyncio.Semaphore(1)` et `_execute` le
   tient pendant tout l'appel du worker (jusqu'à `timeout_s = 900`). Un travail
   spéculatif admis par ce chemin **bloquerait** le tour adressé suivant —
   la violation de D08 telle quelle, et sans préemption possible puisque rien
   dans ce sémaphore ne rend une place.

D'où : bassin propre, exécution propre, priorités propres. Ce qui est repris
sans être redéclaré : `VoiceStateDisposition` pour les dispositions,
`ObservationProvenance` / `PreparedResource` / `ResourceReference` pour ce qui
est rangé, `DiagnosticSink` pour le journal, et la table de capacités du
domaine pour l'autorité.

## Ce qu'un travail ambiant ne peut pas atteindre

`SpeculativeToolbox` est le **seul** moyen par lequel un exécutant emploie un
outil. Elle consulte `SpeculativeGrant` avant de déléguer, et un outil non
accordé n'est jamais appelé — pas « appelé puis annulé » : jamais appelé. Un
outil d'écriture réellement branché dans la boîte reste donc inatteignable, et
chaque tentative est comptée (`tools_refused`) plutôt qu'avalée.

## Priorités et réserve (D08)

Le bassin vaut `MAX_SPECULATIVE_POOL`, dont `RESERVED_EXPLICIT_SLOTS` places
que seul un rang explicite peut prendre. Le spéculatif plafonne donc à
`max_speculative_jobs()`, et **un bassin spéculatif saturé laisse toujours la
réserve libre**. Par-dessus, `note_addressed_turn()` et une admission `P1`
préemptent : les travaux spéculatifs sont annulés du rang le plus bas vers le
plus haut, et du plus récent vers le plus ancien à rang égal — on sacrifie
d'abord ce qui a le moins coûté.

## Ce que la confiance d'un déclencheur ne fait pas

`docs/presentation-ambient-lane.md` §11 prévient que les quatre confiances
(0,6 / 0,5 / 0,5 / 0,3) sont **posées, pas calibrées**. Elles ne sont donc
employées ici que comme **départage** entre deux travaux de même rang, jamais
comme un seuil d'admission : aucune comparaison de la forme
`confidence > x` n'existe dans ce module, et un déclencheur à 0,0 est admis
comme un autre. Le rang vient de la nature du déclencheur, qui est une donnée
close, pas d'un nombre que personne n'a mesuré.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Protocol

from jarvis.core.voice_state import VoiceStateDisposition
from jarvis.domain.ambient_observation import AmbientTrigger
from jarvis.domain.presentation_speculative import (
    EXPLICIT_PRIORITIES,
    MAX_SPECULATIVE_POOL,
    RESERVED_EXPLICIT_SLOTS,
    SPECULATIVE_PRIORITIES,
    SpeculativeAdmission,
    SpeculativeCapability,
    SpeculativeError,
    SpeculativeGrant,
    SpeculativeJobKey,
    SpeculativePriority,
    TRIGGER_PREPARATION,
    job_key_text,
    max_speculative_jobs,
)
from jarvis.domain.interaction_mode import InteractionMode, behaving_interaction_mode
from jarvis.domain.presentation_working_set import (
    ObservationProvenance,
    PreparedResource,
    PresentationObservation,
    ResourceKind,
    ResourceReference,
    ResourceTemperature,
    UtteranceOrigin,
)
from jarvis.domain.v2 import utc_now
from jarvis.ports.v2 import DiagnosticSink

__all__ = [
    "HiddenSceneStager",
    "PreparedFinding",
    "PresentationSpeculativeService",
    "SpeculativeCounters",
    "SpeculativeOutcome",
    "SpeculativePreparationRunner",
    "SpeculativeRequest",
    "SpeculativeToolbox",
]


#: Préfixe des lignes de journal de cette voie, sur le modèle de
#: `presentation.working_set.*` et `presentation.ambient.*`.
SPECULATIVE_KIND = "presentation.speculative"

#: Catégorie de scène par défaut d'un objet préparé. Jeton court, comme le veut
#: `check_token` côté scène.
DEFAULT_STAGE_CATEGORY = "preparation"

#: Deadline d'un travail. Au-delà, il est annulé et compté : une préparation
#: qui dure plus longtemps qu'une présentation ne prépare plus rien d'utile.
DEFAULT_JOB_TIMEOUT_S = 60.0

#: Découvertes retenues d'un travail. Au-delà, le surplus est ignoré et compté :
#: l'ensemble de travail n'en garde que 16 en tout (`MAX_PREPARED_RESOURCES`),
#: donc un exécutant bavard ne doit pas pouvoir vider la collection à lui seul.
MAX_FINDINGS_PER_JOB = 4


# --------------------------------------------------------------------------
# Ce qu'un exécutant reçoit et rend
# --------------------------------------------------------------------------


class SpeculativeToolbox:
    """Le seul chemin d'un exécutant vers un outil. Vérifie, puis délègue.

    `tools` associe un nom d'outil à l'implémentation réelle. La boîte ne
    connaît pas la liste des outils interdits : elle demande au jeton si
    l'outil est **accordé**, et tout le reste est refusé faute d'y être. C'est
    une liste d'autorisation, et c'est ce qui rend l'oubli impossible — un
    outil d'écriture ajouté demain à `tools` reste inatteignable sans qu'une
    ligne de ce fichier change.

    Un refus lève `SpeculativeError` plutôt que de rendre une valeur muette :
    un exécutant qui essaie d'écrire doit s'arrêter, pas continuer avec un
    `None` qu'il prendrait pour un résultat vide.
    """

    def __init__(self, grant: SpeculativeGrant, tools: dict[str, Callable[..., Any]] | None = None):
        if not isinstance(grant, SpeculativeGrant):
            raise SpeculativeError("speculative_toolbox_invalid_grant", "grant doit être un SpeculativeGrant")
        self.grant = grant
        self._tools = dict(tools or {})
        #: Tentatives refusées, par nom d'outil. Lue par le service pour compter,
        #: et par un test pour voir ce qui a été tenté.
        self.refused: list[str] = []

    @property
    def available(self) -> tuple[str, ...]:
        """Les outils réellement appelables : accordés **et** branchés."""

        return tuple(sorted(name for name in self._tools if self.grant.permits(name)))

    async def invoke(self, tool_name: str, *args: Any, **kwargs: Any) -> Any:
        """Employer un outil. Refuse avant d'appeler, jamais après."""

        if not self.grant.permits(tool_name):
            self.refused.append(tool_name if isinstance(tool_name, str) else repr(tool_name))
            self.grant.check(tool_name)  # lève le refus typé, avec l'origine
        tool = self._tools.get(tool_name)
        if tool is None:
            raise SpeculativeError(
                "speculative_tool_unavailable", f"outil accordé mais non branché : {tool_name!r}"
            )
        result = tool(*args, **kwargs)
        return await result if asyncio.iscoroutine(result) else result


@dataclass(frozen=True, slots=True)
class PreparedFinding:
    """Ce qu'un exécutant a trouvé. Une **référence**, jamais une charge utile.

    `stage_hidden` demande en plus un objet de scène masqué : la référence
    rangée pointera alors vers cet objet (`ResourceKind.SCENE_OBJECT`) et non
    vers le locator d'origine, parce que c'est l'objet qui sera révélé.
    """

    kind: ResourceKind
    locator: str
    title: str = ""
    descriptor: dict[str, Any] | None = None
    topic_id: str | None = None
    stage_hidden: bool = False
    stage_category: str = DEFAULT_STAGE_CATEGORY


@dataclass(frozen=True, slots=True)
class SpeculativeRequest:
    """Ce qu'un exécutant reçoit. Du contexte et un jeton, aucune permission d'agir."""

    job_id: str
    key: SpeculativeJobKey
    priority: SpeculativePriority
    grant: SpeculativeGrant
    session_id: str
    utterance_id: str
    text: str
    toolbox: SpeculativeToolbox


@dataclass(frozen=True, slots=True)
class SpeculativeOutcome:
    """Ce qu'un exécutant rend. Des découvertes, et rien d'autre."""

    findings: tuple[PreparedFinding, ...] = ()


class SpeculativePreparationRunner(Protocol):
    """L'exécutant d'un travail. Un sous-agent borné en production, un faux en test.

    Déclaré en `Protocol` pour la même raison que
    `PresentationObservationSink` (Slice 06) : Core et Voice sont deux
    processus, et ce service ne doit connaître ni le CLI, ni le registre
    d'outils, ni le réseau. Aucun composition root ne branche d'exécutant réel
    dans cette Slice — c'est la Slice de déploiement qui le fera, comme pour la
    voie audio (Slice 05) et la voie ambiante (Slice 06).
    """

    async def prepare(self, request: SpeculativeRequest) -> SpeculativeOutcome: ...


class HiddenSceneStager(Protocol):
    """Poser un objet de scène **masqué**, et le révéler plus tard.

    L'autorité d'affichage reste à la scène (D12) : cette voie ne construit pas
    de `SceneCommand`, elle passe par l'outil d'affichage existant, qui impose
    l'acteur, les natures créables et les refus d'épingle et de géométrie.
    """

    async def stage_hidden(self, *, category: str, title: str, summary: str) -> str: ...

    async def reveal(self, object_id: str) -> None: ...


# --------------------------------------------------------------------------
# Compteurs — un invariant qu'on ne peut pas lire est un invariant qui dérive
# --------------------------------------------------------------------------


@dataclass(slots=True)
class SpeculativeCounters:
    """Tout ce que la voie a fait, en nombres. Aucun texte, jamais.

    La Slice 04 a appris le prix d'un invariant invisible : son pire défaut a
    survécu à la revue parce que rien ne pouvait voir l'état qu'il salissait.
    Chaque refus, chaque préemption, chaque disposition du magasin a donc ici
    un compteur, et `stats()` les imprime tous.
    """

    admitted: int = 0
    coalesced: int = 0
    refused_capacity: int = 0
    refused_inactive: int = 0
    refused_stale_session: int = 0
    refused_rejected: int = 0
    preempted: int = 0
    cancelled_session: int = 0
    cancelled_mode: int = 0
    completed: int = 0
    failed: int = 0
    timed_out: int = 0
    findings_received: int = 0
    findings_dropped_bound: int = 0
    findings_invalid: int = 0
    resources_staged: int = 0
    resources_revealed: int = 0
    stage_failures: int = 0
    reveal_failures: int = 0
    tools_refused: int = 0
    results_stale_generation: int = 0
    #: Dispositions rendues par le magasin de la Slice 04, comptées une à une.
    #: Aucune n'est bucketée : une disposition inconnue est dite à `error`.
    store_dispositions: dict[str, int] = field(default_factory=dict)

    def store(self, disposition: VoiceStateDisposition | str) -> None:
        key = disposition.value if isinstance(disposition, VoiceStateDisposition) else str(disposition)
        self.store_dispositions[key] = self.store_dispositions.get(key, 0) + 1

    def to_payload(self) -> dict[str, Any]:
        return {
            name: (dict(value) if isinstance(value, dict) else value)
            for name, value in (
                (field_name, getattr(self, field_name)) for field_name in self.__slots__
            )
        }


@dataclass(slots=True)
class _Job:
    """Un travail en vol. Interne : rien de tout ceci ne sort du service."""

    job_id: str
    key: SpeculativeJobKey
    priority: SpeculativePriority
    grant: SpeculativeGrant
    session_id: str
    utterance_id: str
    text: str
    generation: int
    rank: float
    admitted_seq: int
    joined: int = 1
    task: asyncio.Task | None = None
    cancelled: bool = False

    @property
    def speculative(self) -> bool:
        return self.priority in SPECULATIVE_PRIORITIES

    @property
    def sacrifice_key(self) -> tuple:
        """Ordre du sacrifice : rang le plus bas d'abord, puis le plus récent.

        « Le plus bas d'abord » parce que P4 vaut moins que P2. « Le plus
        récent » à rang égal parce qu'un travail presque fini a déjà coûté ce
        qu'il coûtera, et le jeter ne rend rien.
        """

        return (-int(self.priority), -self.admitted_seq)


# --------------------------------------------------------------------------
# Le service
# --------------------------------------------------------------------------


class PresentationSpeculativeService:
    """Admet, déduplique, plafonne, exécute et range. Une porte par question.

    Synchrone pour l'admission, asynchrone pour l'exécution. Toutes les
    méthodes publiques d'admission rendent une `SpeculativeAdmission` typée et
    ne lèvent jamais : même discipline que le magasin de la Slice 04, pour la
    même raison — une exception se rattrape et se perd, une valeur se compte.
    """

    def __init__(
        self,
        *,
        store: Any,
        runner: SpeculativePreparationRunner,
        stager: HiddenSceneStager | None = None,
        tools: dict[str, Callable[..., Any]] | None = None,
        diagnostics: DiagnosticSink | None = None,
        pool: int = MAX_SPECULATIVE_POOL,
        reserved: int = RESERVED_EXPLICIT_SLOTS,
        job_timeout_s: float = DEFAULT_JOB_TIMEOUT_S,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(pool, bool) or not isinstance(pool, int) or not 1 <= pool <= MAX_SPECULATIVE_POOL:
            raise ValueError("invalid speculative pool size")
        if isinstance(reserved, bool) or not isinstance(reserved, int) or not 0 <= reserved < pool:
            # Une réserve égale au bassin ne laisserait aucune place au
            # spéculatif : la voie existerait sans pouvoir rien préparer.
            raise ValueError("invalid reserved explicit slot count")
        if not isinstance(job_timeout_s, (int, float)) or isinstance(job_timeout_s, bool) or job_timeout_s <= 0:
            raise ValueError("job timeout must be a positive number")
        self._store = store
        self._runner = runner
        self._stager = stager
        self._tools = dict(tools or {})
        self._diagnostics = diagnostics
        self._pool = pool
        self._reserved = reserved
        self._job_timeout_s = float(job_timeout_s)
        self._clock = clock or utc_now
        self._session_id: str | None = None
        self._generation = 0
        self._seq = 0
        self._jobs: dict[str, _Job] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        #: Toutes les tâches vivantes, y compris celles dont la place a déjà été
        #: rendue. Sans cet ensemble, `drain()` et `stop()` n'attendraient que
        #: ce qui est encore inscrit au bassin — donc rien après une préemption,
        #: et un arrêt rendrait la main sur des tâches encore en cours.
        self._tasks: set[asyncio.Task] = set()
        self.counters = SpeculativeCounters()

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def active(self) -> bool:
        return self._session_id is not None

    @property
    def generation(self) -> int:
        """Numéro de vie de la voie. Monte à chaque retrait de séance ou de mode."""

        return self._generation

    @property
    def in_flight(self) -> tuple[str, ...]:
        """Identifiants des travaux en vol, du plus ancien au plus récent."""

        return tuple(job.job_id for job in sorted(self._jobs.values(), key=lambda item: item.admitted_seq))

    @property
    def speculative_in_flight(self) -> int:
        return sum(1 for job in self._jobs.values() if job.speculative)

    @property
    def explicit_in_flight(self) -> int:
        return sum(1 for job in self._jobs.values() if not job.speculative)

    @property
    def free_explicit_slots(self) -> int:
        """Places qu'un rang explicite peut encore prendre, maintenant.

        C'est la valeur qui rend D08 **observable** : elle doit rester
        strictement positive quel que soit le remplissage spéculatif, et un
        test le vérifie sur un bassin spéculatif saturé.
        """

        return max(0, self._pool - len(self._jobs))

    @property
    def max_speculative(self) -> int:
        return max(0, self._pool - self._reserved)

    def stats(self) -> dict[str, Any]:
        """Tout l'état lisible de la voie. Des nombres et des identifiants."""

        return {
            "session_id": self._session_id,
            "generation": self._generation,
            "active": self.active,
            "pool": self._pool,
            "reserved": self._reserved,
            "max_speculative": self.max_speculative,
            "in_flight": len(self._jobs),
            "speculative_in_flight": self.speculative_in_flight,
            "explicit_in_flight": self.explicit_in_flight,
            "free_explicit_slots": self.free_explicit_slots,
            "keys": sorted(job.key.digest for job in self._jobs.values()),
            # Taille de la table de coalescence. Exposée parce que c'est la
            # seule mémoire de la voie qu'une fuite pourrait faire grossir sans
            # que le bassin bouge : sans ce nombre, un test ne peut pas
            # distinguer « la clé est rendue » de « le travail est fini ».
            "tracked_keys": len(self._by_key),
            **self.counters.to_payload(),
        }

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def bind_session(self, session_id: str) -> SpeculativeAdmission:
        """Ouvrir une séance. Lier une autre séance retire d'abord la première."""

        if not isinstance(session_id, str) or not session_id.strip() or session_id != session_id.strip():
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_session_invalid")
        if self._session_id == session_id:
            return SpeculativeAdmission.COALESCED
        if self._session_id is not None:
            self.retire("session_replaced")
        self._session_id = session_id
        self._trace("bound", "Voie spéculative ouverte pour une séance", data={"generation": self._generation})
        return SpeculativeAdmission.ACCEPTED

    def end_session(self, reason: str = "session_ended") -> SpeculativeAdmission:
        return self.retire(reason)

    def retire(self, reason: str) -> SpeculativeAdmission:
        """Fermer la séance et annuler tout ce qui est en vol.

        Le compteur de génération monte **avant** les annulations : un résultat
        qui reviendrait quand même porte alors une génération périmée et est
        refusé par `_normalise`, sans jamais atteindre le magasin.
        """

        if self._session_id is None:
            return SpeculativeAdmission.INACTIVE
        cancelled = self._cancel_all(reason)
        self._session_id = None
        self._generation += 1
        counter = "cancelled_mode" if reason.startswith("interaction_mode_left") else "cancelled_session"
        setattr(self.counters, counter, getattr(self.counters, counter) + cancelled)
        self._trace(
            "retired", "Voie spéculative retirée, travaux annulés",
            data={"reason": reason, "cancelled": cancelled, "generation": self._generation},
        )
        return SpeculativeAdmission.ACCEPTED

    def apply_interaction_mode(self, value: object, *, source: str = "core") -> SpeculativeAdmission:
        """Retirer la voie dès que le mode effectif n'est plus PRESENTATION.

        Même lecture que le magasin de la Slice 04 : `behaving_interaction_mode`,
        la lecture de **comportement**, où un `meeting` réservé ne se comporte
        pas en Presentation.

        Cette lecture ne rend **jamais** `None` : tout ce qu'elle ne sait pas
        lire retombe sur `ASSISTANT`, donc une valeur illisible retire, et c'est
        le bon sens de la panne. Une première version testait `mode is None`
        pour ce cas — une branche morte, et une garde décrite dans une docstring
        que le code n'exerçait pas.
        """

        mode = behaving_interaction_mode(value)
        if mode is InteractionMode.PRESENTATION:
            return SpeculativeAdmission.INACTIVE
        return self.retire(f"interaction_mode_left:{mode.value}:{source}")

    # ------------------------------------------------------------------
    # Admission
    # ------------------------------------------------------------------

    def submit_trigger(self, trigger: object, *, session_id: str | None = None) -> SpeculativeAdmission:
        """Admettre le travail qu'un déclencheur ambiant fait préparer.

        Le rang et les capacités viennent de `TRIGGER_PREPARATION`, une table
        close. Une nature de déclencheur absente de la table est **refusée**,
        pas rangée dans un cas par défaut : si la Slice 06 ajoute une nature un
        jour, cette voie doit décider ce qu'elle en fait, pas l'hériter.
        """

        if not isinstance(trigger, AmbientTrigger):
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_trigger_invalid")
        if getattr(trigger, "authorizes_actions", False):
            # Ne peut pas arriver avec le type réel (`ClassVar` figé à faux).
            # Le contrôle existe pour un transport qui reconstruirait l'objet.
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_trigger_authorizing")
        preparation = TRIGGER_PREPARATION.get(str(trigger.kind.value))
        if preparation is None:
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_trigger_kind_unmapped")
        priority, capabilities = preparation
        key = self._key_for(trigger)
        if key is None:
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_trigger_unkeyable")
        return self._admit(
            key=key, priority=priority, capabilities=capabilities, origin=UtteranceOrigin.AMBIENT,
            session_id=session_id, utterance_id=trigger.utterance_id, text=trigger.text,
            rank=float(trigger.confidence),
        )

    def reserve_explicit(
        self,
        *,
        topic: str,
        capabilities: tuple[SpeculativeCapability, ...],
        utterance_id: str,
        text: str,
        resource: str = "",
        session_id: str | None = None,
    ) -> SpeculativeAdmission:
        """Admettre une préparation demandée par un tour explicite (P1).

        Elle prend une place de la réserve, et son admission **préempte** le
        spéculatif si le bassin est plein : c'est la moitié active de D08, la
        réserve n'en étant que la moitié passive.
        """

        key = self._make_key(topic, resource)
        if key is None:
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_explicit_unkeyable")
        return self._admit(
            key=key, priority=SpeculativePriority.P1_EXPLICIT_PREPARATION, capabilities=capabilities,
            origin=UtteranceOrigin.ADDRESSED, session_id=session_id, utterance_id=utterance_id,
            text=text, rank=1.0,
        )

    def note_addressed_turn(self) -> tuple[str, ...]:
        """Un tour adressé commence (P0) : libérer une place en sacrifiant du spéculatif.

        P0 n'est **jamais admis** dans ce bassin — un tour adressé vit dans le
        cerveau. Cette méthode est la seule chose que cette voie lui doit :
        faire de la place, tout de suite, et dire ce qu'elle a jeté.
        """

        if not self._jobs:
            return ()
        freed = self._preempt(SpeculativePriority.P0_ADDRESSED_TURN, wanted=1)
        return freed

    # ------------------------------------------------------------------
    # Admission — mécanique commune
    # ------------------------------------------------------------------

    def _admit(
        self,
        *,
        key: SpeculativeJobKey,
        priority: SpeculativePriority,
        capabilities: tuple[SpeculativeCapability, ...],
        origin: UtteranceOrigin,
        session_id: str | None,
        utterance_id: str,
        text: str,
        rank: float,
    ) -> SpeculativeAdmission:
        if self._session_id is None:
            return self._refuse(SpeculativeAdmission.INACTIVE, "speculative_lane_inactive")
        if session_id is not None and session_id != self._session_id:
            return self._refuse(SpeculativeAdmission.STALE_SESSION, "speculative_stale_session")
        if priority is SpeculativePriority.P0_ADDRESSED_TURN:
            # Un tour adressé ne se range pas ici : il se réserve une place.
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_addressed_turn_not_admitted")
        try:
            grant = SpeculativeGrant(tuple(capabilities), origin=origin)
        except SpeculativeError as exc:
            return self._refuse(SpeculativeAdmission.REJECTED, exc.code)

        held = self._by_key.get((key.topic_key, key.resource_key))
        if held is not None and held in self._jobs:
            self._jobs[held].joined += 1
            self.counters.coalesced += 1
            self._trace(
                "coalesced", "Travail déjà en vol pour ce sujet et cette ressource",
                data={"job_id": held, "key": key.digest, "joined": self._jobs[held].joined},
            )
            return SpeculativeAdmission.COALESCED

        if priority in EXPLICIT_PRIORITIES:
            if len(self._jobs) >= self._pool:
                self._preempt(priority, wanted=1)
            if len(self._jobs) >= self._pool:
                return self._refuse(SpeculativeAdmission.CAPACITY, "speculative_pool_full")
        elif self.speculative_in_flight >= self.max_speculative:
            # Plafond spéculatif, pas plafond du bassin : la réserve reste
            # libre et un rang explicite passera quand même.
            return self._refuse(SpeculativeAdmission.CAPACITY, "speculative_budget_full")

        self._seq += 1
        job = _Job(
            job_id=f"prep-{self._generation}-{self._seq}", key=key, priority=priority, grant=grant,
            session_id=self._session_id, utterance_id=utterance_id, text=text,
            generation=self._generation, rank=rank, admitted_seq=self._seq,
        )
        self._jobs[job.job_id] = job
        self._by_key[(key.topic_key, key.resource_key)] = job.job_id
        self.counters.admitted += 1
        job.task = asyncio.create_task(self._run(job), name=f"jarvis-presentation-prep-{job.job_id}")
        self._tasks.add(job.task)
        job.task.add_done_callback(self._tasks.discard)
        self._trace(
            "admitted", "Travail de préparation admis",
            data={"job_id": job.job_id, "key": key.digest, "priority": int(priority),
                  "origin": origin.value, "tools": len(grant.allowed_tools),
                  "speculative_in_flight": self.speculative_in_flight,
                  "free_explicit_slots": self.free_explicit_slots},
        )
        return SpeculativeAdmission.ACCEPTED

    def _preempt(self, priority: SpeculativePriority, *, wanted: int) -> tuple[str, ...]:
        """Sacrifier du spéculatif pour un rang explicite. Rend ce qui a été jeté."""

        victims = sorted(
            (job for job in self._jobs.values() if job.speculative and not job.cancelled),
            key=lambda item: item.sacrifice_key,
        )[:wanted]
        for job in victims:
            self._cancel(job, "preempted")
            self.counters.preempted += 1
            self._trace(
                "preempted", "Travail spéculatif sacrifié pour l'interaction explicite",
                data={"job_id": job.job_id, "key": job.key.digest, "victim_priority": int(job.priority),
                      "for_priority": int(priority)},
            )
        return tuple(job.job_id for job in victims)

    # ------------------------------------------------------------------
    # Clés
    # ------------------------------------------------------------------

    def _key_for(self, trigger: AmbientTrigger) -> SpeculativeJobKey | None:
        """Clé d'un déclencheur : sa nature fait le sujet, son texte la ressource.

        Deux déclencheurs de même nature citant le même texte sont le même
        travail. La nature entre dans le sujet parce qu'une même phrase peut
        être à la fois une affirmation à vérifier et une référence à retrouver,
        et ce sont deux préparations différentes.
        """

        return self._make_key(str(trigger.kind.value), trigger.text)

    @staticmethod
    def _make_key(topic: object, resource: object) -> SpeculativeJobKey | None:
        try:
            return SpeculativeJobKey(job_key_text(topic), job_key_text(resource))
        except SpeculativeError:
            return None

    # ------------------------------------------------------------------
    # Exécution
    # ------------------------------------------------------------------

    async def _run(self, job: _Job) -> None:
        """Un travail, du début à sa disparition du bassin. Ne lève jamais.

        Chaque sortie passe par `_release`, y compris l'annulation : un travail
        qui resterait inscrit après sa fin occuperait une place pour toujours,
        et le bassin se fermerait sans que rien ne le dise.
        """

        toolbox = SpeculativeToolbox(job.grant, self._tools)
        request = SpeculativeRequest(
            job_id=job.job_id, key=job.key, priority=job.priority, grant=job.grant,
            session_id=job.session_id, utterance_id=job.utterance_id, text=job.text, toolbox=toolbox,
        )
        try:
            outcome = await asyncio.wait_for(self._runner.prepare(request), timeout=self._job_timeout_s)
        except asyncio.CancelledError:
            self.counters.tools_refused += len(toolbox.refused)
            self._release(job)
            raise
        except asyncio.TimeoutError:
            self.counters.timed_out += 1
            self.counters.tools_refused += len(toolbox.refused)
            self._trace(
                "timeout", "Préparation abandonnée : au-delà de sa limite de temps",
                level="warning", data={"job_id": job.job_id, "timeout_s": self._job_timeout_s},
            )
            self._release(job)
            return
        except Exception as exc:  # noqa: BLE001 - l'échec d'une préparation ne ferme pas la voie
            self.counters.failed += 1
            self.counters.tools_refused += len(toolbox.refused)
            self._trace(
                "failed", f"Préparation en échec : {exc}", level="error",
                data={"job_id": job.job_id, "error_class": type(exc).__name__},
            )
            self._release(job)
            return
        self.counters.tools_refused += len(toolbox.refused)
        if toolbox.refused:
            self._trace(
                "tool_refused", "Outil non accordé refusé à une préparation", level="warning",
                data={"job_id": job.job_id, "origin": job.grant.origin.value,
                      "attempts": len(toolbox.refused), "tools": sorted(set(toolbox.refused))[:8]},
            )
        try:
            await self._normalise(job, outcome)
        except asyncio.CancelledError:
            self._release(job)
            raise
        except Exception as exc:  # noqa: BLE001 - idem : ranger mal ne ferme pas la voie
            self.counters.failed += 1
            self._trace(
                "normalise_failed", f"Rangement d'une préparation en échec : {exc}", level="error",
                data={"job_id": job.job_id, "error_class": type(exc).__name__},
            )
        else:
            self.counters.completed += 1
        self._release(job)

    async def _normalise(self, job: _Job, outcome: object) -> None:
        """Ranger les découvertes dans l'ensemble de travail de la Slice 04.

        Le premier contrôle est celui de la génération : un résultat qui revient
        après un changement de séance ou de mode est **périmé**, et il est
        refusé ici, avant le magasin. Le magasin le refuserait aussi
        (`stale_session`), mais il ne peut pas connaître un retrait de mode qui
        n'a pas encore atteint la séance, et un objet de scène aurait déjà été
        posé entre-temps.
        """

        if job.generation != self._generation or job.session_id != self._session_id:
            self.counters.results_stale_generation += 1
            self._trace(
                "stale_result", "Préparation revenue après un retrait : écartée", level="warning",
                data={"job_id": job.job_id, "job_generation": job.generation,
                      "generation": self._generation},
            )
            return
        if not isinstance(outcome, SpeculativeOutcome):
            self.counters.findings_invalid += 1
            self._trace(
                "outcome_invalid", "Un exécutant a rendu autre chose qu'un résultat typé",
                level="error", data={"job_id": job.job_id, "type": type(outcome).__name__},
            )
            return
        findings = outcome.findings
        self.counters.findings_received += len(findings)
        if len(findings) > MAX_FINDINGS_PER_JOB:
            self.counters.findings_dropped_bound += len(findings) - MAX_FINDINGS_PER_JOB
            self._trace(
                "findings_clipped", "Plus de découvertes que la borne par travail", level="warning",
                data={"job_id": job.job_id, "received": len(findings), "kept": MAX_FINDINGS_PER_JOB},
            )
            findings = findings[:MAX_FINDINGS_PER_JOB]
        for index, finding in enumerate(findings):
            await self._store_finding(job, index, finding)

    async def _store_finding(self, job: _Job, index: int, finding: object) -> None:
        if not isinstance(finding, PreparedFinding):
            self.counters.findings_invalid += 1
            self._trace(
                "finding_invalid", "Découverte qui n'est pas une PreparedFinding", level="error",
                data={"job_id": job.job_id, "index": index, "type": type(finding).__name__},
            )
            return
        resource_id = f"{job.job_id}-r{index}"
        kind, locator = finding.kind, finding.locator
        object_id = ""
        if finding.stage_hidden:
            object_id = await self._stage(job, finding)
            if not object_id:
                return
            # La ressource rangée désigne l'objet masqué : c'est **lui** qu'on
            # révélera, et la scène en est seule propriétaire (D12).
            kind, locator = ResourceKind.SCENE_OBJECT, object_id
        try:
            reference = ResourceReference(
                kind=kind, locator=locator, title=finding.title,
                descriptor=None if finding.stage_hidden else finding.descriptor,
            )
        except (SpeculativeError, TypeError, ValueError) as exc:
            # `ResourceReference` porte déjà le validateur de descripteur et la
            # liste blanche de schémas de la Slice 04 : on ne les refait pas,
            # on compte le refus et on dit lequel.
            self.counters.findings_invalid += 1
            self._trace(
                "finding_refused", f"Référence refusée par le contrat de ressource : {exc}",
                level="warning",
                data={"job_id": job.job_id, "index": index,
                      "code": getattr(exc, "code", type(exc).__name__)},
            )
            return
        provenance = self._provenance(job)
        if provenance is None:
            self.counters.findings_invalid += 1
            self._trace(
                "provenance_missing", "Énonciation absente du fil : provenance introuvable",
                level="warning", data={"job_id": job.job_id, "index": index},
            )
            return
        now = self._clock()
        try:
            resource = PreparedResource(
                resource_id=resource_id, reference=reference, provenance=provenance,
                prepared_at=now, last_used_at=now, temperature=ResourceTemperature.WARM,
                topic_id=finding.topic_id,
            )
            observation = PresentationObservation(
                observation_id=resource_id, session_id=job.session_id, record=resource,
            )
        except (TypeError, ValueError) as exc:
            self.counters.findings_invalid += 1
            self._trace(
                "finding_refused", f"Ressource préparée non constructible : {exc}", level="warning",
                data={"job_id": job.job_id, "index": index, "code": getattr(exc, "code", type(exc).__name__)},
            )
            return
        result = self._store.apply(observation)
        self._account(job, result, resource_id)

    def _account(self, job: _Job, result: Any, resource_id: str) -> None:
        """Compter la disposition du magasin. Aucune n'est bucketée en silence.

        La Slice 06 a payé ce point : une disposition inconnue rangée dans un
        cas par défaut est une régression invisible. Ici elle est dite à
        `error`, comptée sous son propre nom, et ne se confond avec rien.
        """

        disposition = getattr(result, "disposition", None)
        if not isinstance(disposition, VoiceStateDisposition):
            self.counters.store("unknown")
            self._trace(
                "store_disposition_unknown", "Le magasin a répondu une disposition inconnue",
                level="error", data={"job_id": job.job_id, "value": str(disposition)[:64]},
            )
            return
        self.counters.store(disposition)
        if disposition is VoiceStateDisposition.APPLIED:
            self.counters.resources_staged += 1
            self._trace(
                "prepared", "Ressource préparée rangée dans l'ensemble de travail",
                data={"job_id": job.job_id, "resource_id": resource_id,
                      "code": getattr(result, "code", "")},
            )
            return
        level = "info" if disposition in _EXPECTED_STORE else "warning"
        self._trace(
            "store_refused", "Ressource préparée refusée par le magasin", level=level,
            data={"job_id": job.job_id, "resource_id": resource_id,
                  "disposition": disposition.value, "code": getattr(result, "code", "")},
        )

    def _provenance(self, job: _Job) -> ObservationProvenance | None:
        """Le rang réel de l'énonciation, lu dans l'instantané. Jamais inventé.

        La Slice 06 a appris qu'un rang fabriqué rend le retard d'enrichissement
        faux dans le seul sens qui compte. Si l'énonciation a quitté le fil, on
        ne range pas la ressource : une provenance inventée serait pire qu'une
        préparation perdue.
        """

        snapshot = getattr(self._store, "snapshot", None)
        tail = getattr(snapshot, "tail", None)
        for entry in getattr(tail, "entries", ()):  # borné par MAX_TAIL_ENTRIES
            if entry.utterance_id == job.utterance_id:
                return ObservationProvenance(
                    utterance_id=entry.utterance_id, sequence=entry.sequence,
                    observed_at=entry.spoken_at, origin=job.grant.origin,
                )
        return None

    async def _stage(self, job: _Job, finding: PreparedFinding) -> str:
        """Poser l'objet de scène **masqué**. Rend son identifiant, ou la chaîne vide.

        Aucun repli sur un objet visible : si le montage échoue, rien n'est
        rangé. Une préparation qui apparaîtrait à l'écran parce que son montage
        a mal tourné serait exactement ce que « normalement invisible » promet
        de ne jamais faire.
        """

        if self._stager is None:
            self.counters.stage_failures += 1
            self._trace(
                "stage_unavailable", "Aucun monteur de scène branché : rien n'est posé",
                level="warning", data={"job_id": job.job_id},
            )
            return ""
        try:
            object_id = await self._stager.stage_hidden(
                category=finding.stage_category, title=finding.title, summary=finding.locator,
            )
        except Exception as exc:  # noqa: BLE001 - un montage raté ne ferme pas la voie
            self.counters.stage_failures += 1
            self._trace(
                "stage_failed", f"Montage d'un objet masqué en échec : {exc}", level="error",
                data={"job_id": job.job_id, "error_class": type(exc).__name__},
            )
            return ""
        if not isinstance(object_id, str) or not object_id.strip():
            self.counters.stage_failures += 1
            self._trace(
                "stage_failed", "Le monteur n'a pas rendu d'identifiant d'objet", level="error",
                data={"job_id": job.job_id},
            )
            return ""
        return object_id

    # ------------------------------------------------------------------
    # Révélation
    # ------------------------------------------------------------------

    async def reveal(self, resource_id: str) -> SpeculativeAdmission:
        """Rendre visible une ressource montée masquée. Décision de politique.

        Ce chemin n'est **pas** une capacité : aucun travail ne peut l'appeler,
        parce que `scene_set_visibility` n'est accordé par aucune capacité
        (voir l'en-tête du module de domaine). C'est la politique ou un tour
        explicite qui révèle, jamais la préparation elle-même.
        """

        if self._session_id is None:
            return self._refuse(SpeculativeAdmission.INACTIVE, "speculative_lane_inactive")
        snapshot = getattr(self._store, "snapshot", None)
        working_set = getattr(snapshot, "working_set", None)
        resource = next(
            (item for item in getattr(working_set, "resources", ()) if item.resource_id == resource_id),
            None,
        )
        if resource is None:
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_resource_unknown")
        if resource.reference.kind is not ResourceKind.SCENE_OBJECT:
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_resource_not_staged")
        if self._stager is None:
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_stager_unavailable")
        try:
            await self._stager.reveal(resource.reference.locator)
        except Exception as exc:  # noqa: BLE001 - une révélation ratée ne ferme pas la voie
            self.counters.reveal_failures += 1
            self._trace(
                "reveal_failed", f"Révélation d'un objet masqué en échec : {exc}", level="error",
                data={"resource_id": resource_id, "error_class": type(exc).__name__},
            )
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_reveal_failed")
        self.counters.resources_revealed += 1
        result = self._store.use_resource(resource_id, at=self._clock())
        self._account_use(resource_id, result)
        self._trace(
            "revealed", "Ressource préparée révélée", data={"resource_id": resource_id},
        )
        return SpeculativeAdmission.ACCEPTED

    def _account_use(self, resource_id: str, result: Any) -> None:
        disposition = getattr(result, "disposition", None)
        if isinstance(disposition, VoiceStateDisposition):
            self.counters.store(disposition)
            if disposition is not VoiceStateDisposition.APPLIED:
                self._trace(
                    "use_refused", "Le magasin a refusé le réchauffement d'une ressource",
                    level="warning",
                    data={"resource_id": resource_id, "disposition": disposition.value,
                          "code": getattr(result, "code", "")},
                )
            return
        self.counters.store("unknown")
        self._trace(
            "store_disposition_unknown", "Le magasin a répondu une disposition inconnue",
            level="error", data={"resource_id": resource_id, "value": str(disposition)[:64]},
        )

    # ------------------------------------------------------------------
    # Mécanique interne
    # ------------------------------------------------------------------

    def _cancel(self, job: _Job, reason: str) -> None:
        """Annuler un travail et rendre sa place. La raison voyage avec l'annulation.

        `Task.cancel(msg)` porte le motif jusque dans la `CancelledError` : un
        travail sacrifié et un travail dont la séance s'est terminée ne se
        lisent pas pareil dans une trace, et c'est la seule occasion de les
        distinguer.
        """

        job.cancelled = True
        if job.task is not None and not job.task.done():
            job.task.cancel(reason)
        self._release(job)

    def _cancel_all(self, reason: str) -> int:
        count = 0
        for job in tuple(self._jobs.values()):
            self._cancel(job, reason)
            count += 1
        return count

    def _release(self, job: _Job) -> None:
        """Rendre la place. Idempotent : une fin et une annulation peuvent se croiser."""

        self._jobs.pop(job.job_id, None)
        if self._by_key.get((job.key.topic_key, job.key.resource_key)) == job.job_id:
            self._by_key.pop((job.key.topic_key, job.key.resource_key), None)

    def _refuse(self, admission: SpeculativeAdmission, code: str) -> SpeculativeAdmission:
        counter = _REFUSAL_COUNTERS.get(admission)
        if counter is not None:
            setattr(self.counters, counter, getattr(self.counters, counter) + 1)
        self._trace(
            "refused", "Demande de préparation refusée",
            level="info" if admission is SpeculativeAdmission.INACTIVE else "warning",
            data={"admission": admission.value, "code": code},
        )
        return admission

    def _trace(self, event: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        """Journal : des identifiants, des nombres, des codes. Jamais de parole.

        Même règle que la voie ambiante et le magasin : rien de ce qui a été dit
        dans la salle n'entre ici, pas même le texte d'un déclencheur.
        """

        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(
                f"{SPECULATIVE_KIND}.{event}", message, level=level, data=data or {},
            )
        except Exception:  # noqa: BLE001 - un journal en panne n'arrête pas la voie qu'il observe
            pass

    # ------------------------------------------------------------------
    # Aide aux tests et à l'arrêt
    # ------------------------------------------------------------------

    async def drain(self) -> None:
        """Attendre que toute tâche vivante soit terminée ou annulée.

        L'attente porte sur `_tasks` et non sur le bassin : un travail préempté
        a déjà rendu sa place, et l'attendre par le bassin serait ne pas
        l'attendre du tout.
        """

        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def stop(self, reason: str = "lane_stopped") -> None:
        """Arrêter la voie : tout annuler, puis attendre la retombée."""

        self.retire(reason)
        await self.drain()


#: Dispositions attendues d'un magasin qui va bien : elles se journalisent en
#: `info`. Même liste et même raison que `_EXPECTED` de la Slice 04.
_EXPECTED_STORE = frozenset(
    {
        VoiceStateDisposition.DUPLICATE,
        VoiceStateDisposition.IGNORED,
        VoiceStateDisposition.STALE_SESSION,
    }
)

#: Quel compteur monte pour quel refus. Table plutôt que cascade : un refus
#: ajouté sans compteur se voit ici et nulle part ailleurs.
_REFUSAL_COUNTERS: dict[SpeculativeAdmission, str] = {
    SpeculativeAdmission.CAPACITY: "refused_capacity",
    SpeculativeAdmission.INACTIVE: "refused_inactive",
    SpeculativeAdmission.STALE_SESSION: "refused_stale_session",
    SpeculativeAdmission.REJECTED: "refused_rejected",
}
