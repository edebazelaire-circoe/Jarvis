"""La voie de préparation spéculative de Presentation. Bornée, sacrificielle, muette.

Slice 08. Le producteur est la voie ambiante (Slice 06), qui remet des
`AmbientTrigger` ; la sortie est l'ensemble de travail de la Slice 04, plus des
objets de scène **masqués**. Entre les deux, ce service admet, déduplique,
plafonne, exécute, normalise et range — et ne dit jamais rien à voix haute.

## Pourquoi une voie à part, et non `BackBrainTaskService`

`SLICE.md` demande un audit de fraîcheur avant de fabriquer quoi que ce soit.
Il a été fait, et il conclut à la réutilisation du **vocabulaire** et au refus
du **chemin d'exécution**. Deux faits mesurés, tous deux vérifiables :

1. **ce chemin est durable, et D13 l'interdit.** Un travail y est accepté par
   `state.accept_speculative_job` (capacité 16), donc rangé en base et
   recouvrable après redémarrage. La mémoire de Presentation est bornée et
   liée à la séance ; y adosser une préparation ferait survivre à la séance
   ce que D13 dit de ne pas garder. C'est l'argument décisif ;
2. `OwnedJobExecution._slots` est un `asyncio.Semaphore(1)` et `_execute` le
   tient pendant tout l'appel du worker (jusqu'à `timeout_s = 900`). Ce qui
   manque là-bas n'est pas l'annulation — elle existe — mais la
   **concurrence** : un travail spéculatif y occuperait la seule place et
   retarderait le tour adressé suivant, ce que D08 refuse ;
3. accessoirement, son profil d'exécution lance le CLI avec `--tools ""`
   (`jarvis/runtime/claude_local.py`), donc zéro outil, là où D07 demande
   recherche et lecture. Élargir ce profil ne toucherait **pas** le chemin
   adressé — `back_brain_worker.py` ne choisit `speculative_analysis` que pour
   un travail spéculatif, l'adressé restant sur `job_result` — mais changerait
   ce que voient les consommateurs actuels de `speculative_analysis`
   (`live_delegation.py`). Argument réel, et le plus faible des trois.

D'où : bassin propre, exécution propre, priorités propres. Ce qui est repris
sans être redéclaré : `VoiceStateDisposition` pour les dispositions,
`ObservationProvenance` / `PreparedResource` / `ResourceReference` pour ce qui
est rangé, `DiagnosticSink` pour le journal, et la table de capacités du
domaine pour l'autorité.

## Ce qu'un travail ambiant ne peut pas atteindre

Le jeton (`SpeculativeGrant`) est la frontière, et `grant.allowed_tools` est ce
qu'un exécutant de production recevra pour construire son `--tools`. Un jeton
d'origine ambiante ne peut pas même se **construire** avec une capacité hors
`AMBIENT_CAPABILITIES` : le refus est dans `__post_init__`, pas chez
l'appelant.

Et surtout : **le montage d'un objet de scène est gardé par cette même table**.
C'est le seul effet de cette voie qui atteigne un état durable, et une première
version était la seule chose que la table ne gardait pas — un travail ambiant
`new_topic`, sans un seul outil de scène dans son jeton, créait quand même un
objet. `_store_finding` consulte maintenant `grant.may_stage`.

## Priorités et réserve (D08)

Le bassin vaut `MAX_SPECULATIVE_POOL`, dont `RESERVED_EXPLICIT_SLOTS` places
que seul un rang explicite peut prendre. Le spéculatif plafonne donc à
`self.max_speculative`, et **un bassin spéculatif saturé laisse toujours la
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
from typing import Any, Callable, Iterable, Protocol, Sequence

from jarvis.core.voice_state import VoiceStateDisposition
from jarvis.domain.ambient_observation import AmbientTrigger
from jarvis.domain.presentation_attention import FactCheckAssessment
from jarvis.domain.presentation_speculative import (
    AMBIENT_CAPABILITIES,
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
    STAGING_CAPABILITY,
    TRIGGER_PREPARATION,
    job_key_text,
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
    "AttentionRaiser",
    "HiddenSceneStager",
    "PreparedFinding",
    "PresentationSpeculativeService",
    "SpeculativeCounters",
    "SpeculativeOutcome",
    "SpeculativePreparationRunner",
    "SpeculativeRequest",
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

#: Objets de scène montés que cette voie garde ouverts en même temps.
#:
#: Un objet de scène est **durable** : il descend jusqu'à `INSERT INTO
#: scene_objects` et survit au redémarrage. Sans plafond ni reprise, chaque
#: préparation en laissait un pour toujours, comptant contre les 512 de
#: `MAX_SCENE_OBJECTS` jusqu'à ce que la scène réponde `SCENE_FULL`. Huit, soit
#: la moitié des seize ressources préparées que le magasin retient : monter plus
#: d'écrans qu'on n'en montrera jamais n'aide personne.
MAX_STAGED_OBJECTS = 8


# --------------------------------------------------------------------------
# Ce qu'un exécutant reçoit et rend
# --------------------------------------------------------------------------


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


@dataclass(frozen=True, slots=True)
class SpeculativeOutcome:
    """Ce qu'un exécutant rend. Des découvertes, et des verdicts de vérification.

    `findings` sont des **références** : des pistes rangées dans l'ensemble de
    travail. `assessments` est ce que la Slice 09 a dû ajouter, parce que cette
    voie n'avait aucun moyen de dire *« l'affirmation est contredite »* : une
    piste n'est pas un jugement, et la page contractuelle de la Slice 08 le
    disait déjà — *« une ressource de vérification préparée est une piste ;
    l'attention est la Slice 09 »*.

    Un verdict ne nomme ni sa catégorie, ni sa gravité, ni son identifiant :
    tout cela est calculé par `decide_attention`. Un exécutant qui rend un
    verdict sans en avoir la capacité est refusé et compté, jamais promu.
    """

    findings: tuple[PreparedFinding, ...] = ()
    assessments: tuple[FactCheckAssessment, ...] = ()


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

    async def discard(self, object_ids: "Sequence[str]") -> None: ...


class AttentionRaiser(Protocol):
    """Qui juge un verdict de vérification et le signale, ou le refuse.

    Déclaré en `Protocol` pour la même raison que les deux au-dessus : cette
    voie ne doit rien savoir de l'ensemble de travail au-delà de son magasin,
    ni de la trace, ni de la surface qui montrera l'avertissement. L'unique
    implantation de production est
    `jarvis.core.presentation_attention.PresentationAttentionService`.

    `may_verify` est passé par la voie et non déduit par l'appelé : c'est le
    jeton du travail qui l'ouvre, et il n'y a qu'un endroit qui connaît le
    jeton.
    """

    def raise_from_assessments(
        self,
        assessments: Iterable[object],
        *,
        job_id: str,
        session_id: str,
        may_verify: bool,
    ) -> tuple: ...


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
    stage_refused: int = 0
    staged_objects_discarded: int = 0
    discard_failures: int = 0
    reveal_failures: int = 0
    #: Échecs du puits de diagnostic lui-même. Sans ce compteur, un journal
    #: cassé rend la voie muette tout en la laissant se déclarer en bonne
    #: santé — même raison et même nom que `OwnedJobExecution.diagnostic_failures`.
    diagnostic_failures: int = 0
    results_stale_generation: int = 0
    #: Verdicts de vérification reçus d'un exécutant (Slice 09).
    assessments_received: int = 0
    #: Verdicts écartés parce que le jeton du travail n'ouvre pas la
    #: vérification. Comptés **d'après la réponse du juge**, et non par une
    #: seconde porte posée ici : une première version décidait la capacité des
    #: deux côtés, et passait ensuite `may_verify=True` en dur au juge — de
    #: sorte que son propre contrôle et `attention_capability_missing` étaient
    #: injoignables en production. Deux gardes pour une règle, dont une morte.
    assessments_refused_capability: int = 0
    #: Le juge a **levé**. Compté à part de `failed`, qui dit « une préparation
    #: a échoué » : confondre les deux rendait invisible lequel des deux étages
    #: était en panne.
    attention_failures: int = 0
    #: Verdicts arrivés sans qu'aucun juge ne soit branché. Le cas normal
    #: aujourd'hui — aucun composition root ne branche cette voie — mais un
    #: silence ne doit pas se confondre avec un refus.
    assessments_unjudged: int = 0
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
        attention: AttentionRaiser | None = None,
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
        self._attention = attention
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
        #: Objets de scène montés par cette voie et pas encore repris. C'est la
        #: seule trace durable qu'elle laisse, donc la seule qu'elle doit
        #: savoir effacer (D13).
        self._staged: list[str] = []
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
            "staged_objects": len(self._staged),
            "staged_budget": MAX_STAGED_OBJECTS,
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
        # La génération monte **avant** les annulations : un résultat qui
        # reviendrait quand même porte alors une génération périmée et
        # `_normalise` le refuse. L'ordre inverse laisserait une fenêtre le jour
        # où un `await` s'intercale ici — et une première version documentait
        # cet ordre tout en faisant le contraire.
        self._generation += 1
        cancelled = self._cancel_all(reason)
        self._session_id = None
        self._reclaim_staged(reason)
        counter = "cancelled_mode" if reason.startswith("interaction_mode_left") else "cancelled_session"
        setattr(self.counters, counter, getattr(self.counters, counter) + cancelled)
        self._trace(
            "retired", "Voie spéculative retirée, travaux annulés",
            data={"reason": reason, "cancelled": cancelled, "generation": self._generation},
        )
        return SpeculativeAdmission.ACCEPTED

    def _reclaim_staged(self, reason: str) -> None:
        """Reprendre les objets de scène montés. D13 : rien ne survit à la séance.

        Un objet de scène est durable — il est rangé en base et survit au
        redémarrage — donc « la séance est finie » ne suffit pas à le faire
        disparaître : il faut le dire à la scène. Sans cela, chaque préparation
        laissait un objet masqué pour toujours, qu'un
        `scene_set_visibility(scope="all_hidden")` du cerveau pouvait ensuite
        révéler en bloc, avec tout ce que l'utilisateur n'avait jamais demandé.

        La reprise est **planifiée** plutôt qu'attendue : `retire()` est
        synchrone parce qu'il est appelé depuis l'écoute du mode (Slice 02), qui
        notifie sans `await`. L'échec d'une reprise est compté et dit, jamais
        avalé.
        """

        pending, self._staged = tuple(self._staged), []
        if not pending or self._stager is None:
            if pending:
                self.counters.discard_failures += len(pending)
                self._trace(
                    "discard_unavailable",
                    "Objets montés abandonnés : aucun monteur pour les reprendre",
                    level="error", data={"objects": len(pending), "reason": reason},
                )
            return
        task = asyncio.ensure_future(self._discard(pending, reason))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _discard(self, object_ids: tuple[str, ...], reason: str) -> None:
        try:
            await self._stager.discard(object_ids)
        except Exception as exc:  # noqa: BLE001 - une reprise ratée ne ferme pas la voie
            self.counters.discard_failures += len(object_ids)
            self._trace(
                "discard_failed", "Reprise des objets montés en échec", level="error",
                data={"objects": len(object_ids), "reason": reason,
                      "error_class": type(exc).__name__},
            )
            return
        self.counters.staged_objects_discarded += len(object_ids)
        self._trace(
            "discarded", "Objets de scène montés repris", data={"objects": len(object_ids), "reason": reason},
        )

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

        if self.free_explicit_slots > 0:
            # Il reste de la place : D08 demande que l'interaction explicite
            # passe, pas qu'on jette du travail utile pour le plaisir. Une
            # première version sacrifiait un travail alors que sept places
            # étaient libres.
            return ()
        return self._preempt(SpeculativePriority.P0_ADDRESSED_TURN, wanted=1)

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
            return self._refuse(SpeculativeAdmission.INACTIVE, "speculative_lane_inactive", key=key)
        if session_id is not None and session_id != self._session_id:
            return self._refuse(SpeculativeAdmission.STALE_SESSION, "speculative_stale_session", key=key)
        if priority is SpeculativePriority.P0_ADDRESSED_TURN:
            # Un tour adressé ne se range pas ici : il se réserve une place.
            return self._refuse(
                SpeculativeAdmission.REJECTED, "speculative_addressed_turn_not_admitted", key=key
            )
        try:
            grant = SpeculativeGrant(tuple(capabilities), origin=origin)
        except SpeculativeError as exc:
            return self._refuse(SpeculativeAdmission.REJECTED, exc.code, key=key)

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
                return self._refuse(SpeculativeAdmission.CAPACITY, "speculative_pool_full", key=key)
        elif self.speculative_in_flight >= self.max_speculative:
            # Plafond spéculatif, pas plafond du bassin : la réserve reste
            # libre et un rang explicite passera quand même.
            return self._refuse(SpeculativeAdmission.CAPACITY, "speculative_budget_full", key=key)

        self._seq += 1
        job = _Job(
            job_id=f"prep-{self._generation}-{self._seq}", key=key, priority=priority, grant=grant,
            session_id=self._session_id, utterance_id=utterance_id, text=text,
            generation=self._generation, rank=rank, admitted_seq=self._seq,
        )
        runnable = self._run(job)
        try:
            job.task = asyncio.create_task(
                runnable, name=f"jarvis-presentation-prep-{job.job_id}"
            )
        except RuntimeError:
            runnable.close()  # sinon « coroutine was never awaited » à la collecte
            # Pas de boucle en cours. Sans cette garde `submit_trigger` levait,
            # contrairement à sa docstring — et comme Slice 06 rattrape ce que
            # son consommateur de déclencheurs lève, la panne aurait été comptée
            # par la voie **ambiante** et n'aurait paru nulle part ici.
            return self._refuse(SpeculativeAdmission.INACTIVE, "speculative_no_event_loop", key=key)
        self._jobs[job.job_id] = job
        self._by_key[(key.topic_key, key.resource_key)] = job.job_id
        self.counters.admitted += 1
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

        request = SpeculativeRequest(
            job_id=job.job_id, key=job.key, priority=job.priority, grant=job.grant,
            session_id=job.session_id, utterance_id=job.utterance_id, text=job.text,
        )
        try:
            outcome = await asyncio.wait_for(self._runner.prepare(request), timeout=self._job_timeout_s)
        except asyncio.CancelledError:
            self._release(job)
            raise
        except asyncio.TimeoutError:
            self.counters.timed_out += 1
            self._trace(
                "timeout", "Préparation abandonnée : au-delà de sa limite de temps",
                level="warning", data={"job_id": job.job_id, "timeout_s": self._job_timeout_s},
            )
            self._release(job)
            return
        except Exception as exc:  # noqa: BLE001 - l'échec d'une préparation ne ferme pas la voie
            self.counters.failed += 1
            self._trace(
                "failed", "Préparation en échec", level="error",
                data={"job_id": job.job_id, "error_class": type(exc).__name__},
            )
            self._release(job)
            return
        try:
            await self._normalise(job, outcome)
        except asyncio.CancelledError:
            self._release(job)
            raise
        except Exception as exc:  # noqa: BLE001 - idem : ranger mal ne ferme pas la voie
            self.counters.failed += 1
            self._trace(
                "normalise_failed", "Rangement d'une préparation en échec", level="error",
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
        self._raise_attention(job, outcome.assessments)

    def _raise_attention(self, job: _Job, assessments: object) -> None:
        """Remettre les verdicts au juge, s'il y en a et si le jeton l'ouvre.

        **La capacité est lue ici**, parce que c'est ici qu'est le jeton. La
        Slice 08 a payé cette leçon au prix fort : son seul effet durable était
        le seul que la table de capacités ne gardait pas. L'alerte est un effet
        du même genre — elle range un enregistrement et elle fait du bruit —
        donc elle passe par la table, et un travail dont le jeton n'ouvre pas
        `FACT_VERIFICATION` ne peut pas alerter, quoi qu'il rende.

        Ne lève jamais : un juge en panne ne doit pas faire compter la
        préparation comme un échec de rangement.
        """

        if not isinstance(assessments, tuple) or not assessments:
            return
        self.counters.assessments_received += len(assessments)
        # **Le jeton est lu ici, la décision est prise là-bas.** Cette voie est
        # le seul endroit qui connaisse le jeton, donc elle le lit ; mais elle
        # passe la valeur au juge au lieu d'en tirer elle-même un refus, pour
        # qu'il n'existe qu'un seul décideur. Le refus se compte ensuite à la
        # lecture de sa réponse.
        may_verify = SpeculativeCapability.FACT_VERIFICATION in job.grant.capabilities
        if not may_verify:
            self._trace(
                "assessment_refused", "Verdict sans capacité de vérification : remis au juge, qui refusera",
                level="warning",
                data={"job_id": job.job_id, "origin": job.grant.origin.value,
                      "required": SpeculativeCapability.FACT_VERIFICATION.value,
                      "held": sorted(c.value for c in job.grant.capabilities),
                      "count": len(assessments)},
            )
        if self._attention is None:
            self.counters.assessments_unjudged += len(assessments)
            self._trace(
                "attention_unavailable", "Verdict reçu sans juge branché : aucun signal",
                level="warning", data={"job_id": job.job_id, "count": len(assessments)},
            )
            return
        try:
            decisions = self._attention.raise_from_assessments(
                assessments, job_id=job.job_id, session_id=job.session_id,
                may_verify=may_verify,
            )
        except Exception as exc:  # noqa: BLE001 - un juge en panne ne ferme pas la voie
            self.counters.attention_failures += 1
            self._trace(
                "attention_failed", "Le juge d'attention a échoué", level="error",
                data={"job_id": job.job_id, "error_class": type(exc).__name__},
            )
            return
        for decision in decisions or ():
            if getattr(getattr(decision, "refusal", None), "value", "") \
                    == "attention_capability_missing":
                self.counters.assessments_refused_capability += 1

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
            if not job.grant.may_stage:
                # B2. Le montage est le **seul** effet de cette voie qui
                # atteigne un état durable, et c'était le seul que la table de
                # capacités ne gardait pas : tout ce qu'elle gardait était en
                # lecture seule. Un travail ambiant `new_topic`, dont le jeton
                # ne porte aucun outil de scène, créait quand même un objet.
                self.counters.stage_refused += 1
                self._trace(
                    "stage_refused", "Montage refusé : la capacité n'est pas accordée",
                    level="warning",
                    data={"job_id": job.job_id, "origin": job.grant.origin.value,
                          "required": STAGING_CAPABILITY.value,
                          "held": sorted(c.value for c in job.grant.capabilities)},
                )
                return
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
                "finding_refused", "Référence refusée par le contrat de ressource", level="warning",
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
                "finding_refused", "Ressource préparée non constructible", level="warning",
                data={"job_id": job.job_id, "index": index, "code": getattr(exc, "code", type(exc).__name__)},
            )
            return
        result = self._store.apply(observation)
        self._account(job, result, resource_id)

    def _account(self, job: "_Job | None", result: Any, resource_id: str) -> None:
        """Compter la disposition du magasin. Aucune n'est bucketée en silence.

        La Slice 06 a payé ce point : une disposition inconnue rangée dans un
        cas par défaut est une régression invisible. Ici elle est dite à
        `error`, comptée sous son propre nom, et ne se confond avec rien.
        """

        job_id = job.job_id if job is not None else ""
        disposition = getattr(result, "disposition", None)
        if not isinstance(disposition, VoiceStateDisposition):
            self.counters.store("unknown")
            self._trace(
                "store_disposition_unknown", "Le magasin a répondu une disposition inconnue",
                level="error", data={"job_id": job_id, "value": str(disposition)[:64]},
            )
            return
        self.counters.store(disposition)
        if disposition is VoiceStateDisposition.APPLIED:
            self.counters.resources_staged += 1
            self._trace(
                "prepared", "Ressource préparée rangée dans l'ensemble de travail",
                data={"job_id": job_id, "resource_id": resource_id,
                      "code": getattr(result, "code", "")},
            )
            return
        level = "info" if disposition in _EXPECTED_STORE else "warning"
        self._trace(
            "store_refused", "Ressource préparée refusée par le magasin", level=level,
            data={"job_id": job_id, "resource_id": resource_id,
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
        if len(self._staged) >= MAX_STAGED_OBJECTS:
            # Un objet de scène est durable : sans ce plafond, une séance
            # bavarde remplit la scène jusqu'à `SCENE_FULL` et gêne le
            # cerveau, pour des écrans que personne n'a demandés.
            self.counters.stage_refused += 1
            self._trace(
                "stage_budget_full", "Plafond d'objets montés atteint : rien n'est posé",
                level="warning",
                data={"job_id": job.job_id, "staged": len(self._staged),
                      "budget": MAX_STAGED_OBJECTS},
            )
            return ""
        try:
            object_id = await self._stager.stage_hidden(
                category=finding.stage_category, title=finding.title, summary=finding.locator,
            )
        except Exception as exc:  # noqa: BLE001 - un montage raté ne ferme pas la voie
            self.counters.stage_failures += 1
            self._trace(
                "stage_failed", "Montage d'un objet masqué en échec", level="error",
                data={"job_id": job.job_id, "error_class": type(exc).__name__,
                      "code": getattr(exc, "code", "")},
            )
            return ""
        if not isinstance(object_id, str) or not object_id.strip():
            self.counters.stage_failures += 1
            self._trace(
                "stage_failed", "Le monteur n'a pas rendu d'identifiant d'objet", level="error",
                data={"job_id": job.job_id},
            )
            return ""
        self._staged.append(object_id)
        self._trace(
            "staged", "Objet de scène monté masqué",
            data={"job_id": job.job_id, "object_id": object_id, "staged": len(self._staged)},
        )
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
                "reveal_failed", "Révélation d'un objet masqué en échec", level="error",
                data={"resource_id": resource_id, "error_class": type(exc).__name__},
            )
            return self._refuse(SpeculativeAdmission.REJECTED, "speculative_reveal_failed")
        self.counters.resources_revealed += 1
        result = self._store.use_resource(resource_id, at=self._clock())
        self._account(None, result, resource_id)
        self._trace(
            "revealed", "Ressource préparée révélée", data={"resource_id": resource_id},
        )
        return SpeculativeAdmission.ACCEPTED

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

    def _refuse(
        self, admission: SpeculativeAdmission, code: str, *, key: SpeculativeJobKey | None = None
    ) -> SpeculativeAdmission:
        """Compter et dire un refus. Avec l'empreinte du sujet quand elle existe.

        Sans elle, « pourquoi Jarvis n'a-t-il rien préparé sur ce sujet ? » se
        lisait dans une suite de lignes indifférenciées, alors que toutes les
        autres branches — admise, coalescée, préemptée — nomment leur sujet.
        """

        counter = _REFUSAL_COUNTERS.get(admission)
        if counter is not None:
            setattr(self.counters, counter, getattr(self.counters, counter) + 1)
        self._trace(
            "refused", "Demande de préparation refusée",
            level="info" if admission is SpeculativeAdmission.INACTIVE else "warning",
            data={"admission": admission.value, "code": code,
                  "key": key.digest if key is not None else ""},
        )
        return admission

    def _trace(self, event: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        """Journal : des identifiants, des nombres, des codes. Jamais de parole.

        Même règle que la voie ambiante et le magasin : rien de ce qui a été dit
        dans la salle n'entre ici, pas même le texte d'un déclencheur.

        **Et pas davantage le texte d'une exception.** C'est la seule entorse
        assumée à « toute panne se raconte dans ses propres mots » : un
        exécutant reçoit `request.text`, c'est-à-dire de la parole, et n'importe
        lequel qui renvoie son entrée dans un message d'erreur la déposerait
        ici, au niveau `error`, dans un fichier durable. Une première version
        interpolait `{exc}` à cinq endroits et trois fuyaient. Les lignes
        portent donc `error_class` et un code stable ; le texte complet d'une
        panne appartient au canal de l'exécutant, pas à la trace de la salle.
        """

        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(
                f"{SPECULATIVE_KIND}.{event}", message, level=level, data=data or {},
            )
        except Exception:  # noqa: BLE001 - un journal en panne n'arrête pas la voie qu'il observe
            # Mais il se compte. Sans ce compteur, un puits cassé rend la trace
            # vide pendant que `stats()` annonce une voie en bonne santé : les
            # deux seules lectures disponibles disent alors « tout va bien » et
            # « il ne se passe rien », ce qui est exactement l'ambiguïté que le
            # reste de ce module combat. Il n'y a pas de second canal où le
            # dire, d'où un nombre plutôt qu'une ligne.
            self.counters.diagnostic_failures += 1

    # ------------------------------------------------------------------
    # Aide aux tests et à l'arrêt
    # ------------------------------------------------------------------

    async def drain(self) -> None:
        """Attendre que toute tâche vivante soit terminée ou annulée.

        L'attente porte sur `_tasks` et non sur le bassin : un travail préempté
        a déjà rendu sa place, et l'attendre par le bassin serait ne pas
        l'attendre du tout.
        """

        while True:
            pending = tuple(self._tasks)
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)
            # Retirer soi-même ce qui est terminé. S'en remettre au rappel
            # `done` ne marche pas : attendre un `gather` dont tous les enfants
            # sont **déjà** terminés ne suspend pas, donc les rappels en attente
            # ne tournent jamais et la boucle tourne à vide pour toujours. Une
            # première version faisait exactement cela — 710 550 tours en deux
            # secondes, et un `stop()` dont on ne revenait pas.
            self._tasks.difference_update({task for task in pending if task.done()})

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
