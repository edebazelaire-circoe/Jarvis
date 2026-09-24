"""Préparation spéculative de Presentation : ce qu'un travail ambiant a le droit de faire.

Slice 08 de `jarvis-presentation-interaction-mode`. Décisions **D03** (une
parole ambiante n'autorise aucune action), **D07** (le travail spéculatif reste
agentique), **D08** (il est sacrificiel), **D12** (la scène garde son autorité),
**D13** (rien n'est persisté).

Ce module est **pur** : ni magasin, ni agent, ni scène, ni réseau, ni horloge.
Il porte deux choses et rien d'autre — le vocabulaire de la voie spéculative, et
**la table des capacités**.

## La frontière d'autorité est une donnée

La règle « l'ambiant peut chercher, jamais écrire » ne vit pas dans une phrase
de docstring qu'un lecteur pressé enjambe : elle vit dans
`CAPABILITY_TOOLS`, une table close de capacité vers outils, et dans
`SPECULATIVE_TOOL_RISK`, qui donne à chaque outil nommé son niveau de risque.
Le niveau de risque est `jarvis.domain.actions.RiskLevel` — celui que
`jarvis/security/policy.py` utilise déjà pour `V1_ACTION_POLICY` — et **non** un
second vocabulaire pour la même question.

L'invariant est vérifié au **chargement du module** (`_check_capability_table`) :
tout outil accordé par une capacité doit être déclaré dans
`SPECULATIVE_TOOL_RISK` avec un risque `READ` ou `EPHEMERAL`, et ne doit pas
figurer dans `FORBIDDEN_TOOL_NAMES`. Ajouter `RiskLevel.WRITE` à une capacité
casse l'import du module, donc tout le paquet : la faute ne peut pas se cacher
dans une branche rarement prise.

`SpeculativeGrant.permits` est une **liste d'autorisation**, jamais une liste
d'interdiction : un outil inconnu est refusé parce qu'il est inconnu, pas parce
qu'on avait pensé à l'interdire. C'est la leçon de la Slice 04 sur les schémas
d'URL et de la Slice 06 sur les gardes d'import, appliquée ici.

## Ce qui n'est délibérément accordé à personne

`scene_set_visibility` n'appartient à **aucune** capacité. Un travail ambiant
prépare un objet de scène masqué ; le rendre visible est une décision de
politique ou de tour explicite, jamais un geste du travail lui-même. Sans cette
séparation, « normalement invisible » redeviendrait une intention plutôt qu'une
propriété.

## Les priorités

`P0`/`P1` sont explicites et protégées, `P2`/`P3`/`P4` sont spéculatives et
sacrificielles (D08). `P0` n'est jamais admis ici : c'est le tour adressé, qui
vit dans le cerveau, et cette voie ne fait que lui **réserver** de la place.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from hashlib import sha256
from typing import ClassVar

from jarvis.domain.actions import RiskLevel
from jarvis.domain.presentation_working_set import (
    MAX_PRESENTATION_ID_CHARS,
    UtteranceOrigin,
)
from jarvis.security.policy import FORBIDDEN_TOOL_NAMES

__all__ = [
    "CAPABILITY_TOOLS",
    "EXPLICIT_PRIORITIES",
    "MAX_SPECULATIVE_JOB_KEY_CHARS",
    "MAX_SPECULATIVE_POOL",
    "RESERVED_EXPLICIT_SLOTS",
    "SPECULATIVE_PRIORITIES",
    "SPECULATIVE_TOOL_RISK",
    "SpeculativeAdmission",
    "SpeculativeCapability",
    "SpeculativeError",
    "SpeculativeGrant",
    "SpeculativeJobKey",
    "SpeculativePriority",
    "TRIGGER_PREPARATION",
    "job_key_text",
    "max_speculative_jobs",
]


# --------------------------------------------------------------------------
# Refus typé
# --------------------------------------------------------------------------


class SpeculativeError(ValueError):
    """Refus typé, code stable et ASCII, message pour l'humain.

    Même forme que `PresentationWorkingSetError` (Slice 04) et
    `AmbientObservationError` (Slice 06) : une surface peut se brancher sur le
    code sans lire le message.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# Capacités — la frontière, en données
# --------------------------------------------------------------------------


class SpeculativeCapability(StrEnum):
    """Ce qu'un travail spéculatif a le droit de faire. Ensemble clos.

    La liste vient mot pour mot de D07 et de `SLICE.md` : recherche, résolution
    de document, inspection de code, veille web, analyse de données,
    vérification de fait, préparation d'affichage. Il n'existe aucune valeur
    « écrire », « envoyer », « exécuter » ou « se souvenir » — et en ajouter une
    ferait tomber `_check_capability_table` au chargement si elle accordait le
    moindre outil mutant.
    """

    RESEARCH_SEARCH = "research_search"
    DOCUMENT_RESOLUTION = "document_resolution"
    CODE_INSPECTION = "code_inspection"
    WEB_NEWS_LOOKUP = "web_news_lookup"
    DATA_ANALYSIS = "data_analysis"
    FACT_VERIFICATION = "fact_verification"
    DISPLAY_PREPARATION = "display_preparation"


#: Niveau de risque de chaque outil que cette voie sait nommer.
#:
#: `RiskLevel` est repris de `jarvis/domain/actions.py`, le vocabulaire que
#: `V1_ACTION_POLICY` emploie déjà. `EPHEMERAL` est le niveau de
#: `BOARD_PRESENT` : une chose qui apparaît pour la séance et ne survit pas —
#: exactement ce qu'est un objet de scène. Rien ici n'est `WRITE`, et c'est
#: `_check_capability_table` qui le tient, pas cette phrase.
SPECULATIVE_TOOL_RISK: dict[str, RiskLevel] = {
    "Read": RiskLevel.READ,
    "Glob": RiskLevel.READ,
    "Grep": RiskLevel.READ,
    "WebSearch": RiskLevel.READ,
    "WebFetch": RiskLevel.READ,
    "memory_search": RiskLevel.READ,
    "scene_inspect": RiskLevel.READ,
    "scene_query": RiskLevel.READ,
    "scene_get": RiskLevel.READ,
    "scene_create_object": RiskLevel.EPHEMERAL,
    "scene_update_object": RiskLevel.EPHEMERAL,
}

#: Risques qu'une capacité spéculative peut accorder. `WRITE` en est absent, et
#: c'est le seul endroit où cette exclusion est écrite.
GRANTABLE_RISKS: frozenset[RiskLevel] = frozenset({RiskLevel.READ, RiskLevel.EPHEMERAL})


#: Ce que chaque capacité accorde. Table close, lue par `SpeculativeGrant`.
#:
#: `scene_set_visibility` n'y figure nulle part : voir l'en-tête du module.
CAPABILITY_TOOLS: dict[SpeculativeCapability, frozenset[str]] = {
    SpeculativeCapability.RESEARCH_SEARCH: frozenset(
        {"WebSearch", "Grep", "Glob", "memory_search"}
    ),
    SpeculativeCapability.DOCUMENT_RESOLUTION: frozenset({"Read", "Glob", "Grep"}),
    SpeculativeCapability.CODE_INSPECTION: frozenset({"Read", "Glob", "Grep"}),
    SpeculativeCapability.WEB_NEWS_LOOKUP: frozenset({"WebSearch", "WebFetch"}),
    SpeculativeCapability.DATA_ANALYSIS: frozenset({"Read", "Glob"}),
    SpeculativeCapability.FACT_VERIFICATION: frozenset(
        {"WebSearch", "WebFetch", "Read", "memory_search"}
    ),
    SpeculativeCapability.DISPLAY_PREPARATION: frozenset(
        {"scene_inspect", "scene_query", "scene_get", "scene_create_object", "scene_update_object"}
    ),
}


def _check_capability_table() -> None:
    """Vérifier la table au chargement du module. Une faute casse l'import.

    Trois contrôles, dans cet ordre :

    1. chaque capacité de l'énumération a une entrée — une capacité ajoutée
       sans table accorderait silencieusement l'ensemble vide, ce qui se lit
       comme « ça ne marche pas » et jamais comme « la table est incomplète » ;
    2. chaque outil accordé est déclaré dans `SPECULATIVE_TOOL_RISK` ;
    3. son risque est `GRANTABLE_RISKS`, et son nom n'est pas dans
       `FORBIDDEN_TOOL_NAMES` (comparé en minuscules : cette liste-là est
       écrite en minuscules et « Bash » ne doit pas passer à côté de « bash »).
    """

    missing = set(SpeculativeCapability) - set(CAPABILITY_TOOLS)
    if missing:
        raise RuntimeError(f"speculative capability without a tool table: {sorted(missing)}")
    forbidden_lower = {name.lower() for name in FORBIDDEN_TOOL_NAMES}
    for capability, tools in CAPABILITY_TOOLS.items():
        if not isinstance(tools, frozenset) or not tools:
            raise RuntimeError(f"capability {capability} must grant a non-empty frozenset")
        for tool in tools:
            risk = SPECULATIVE_TOOL_RISK.get(tool)
            if risk is None:
                raise RuntimeError(f"capability {capability} grants undeclared tool {tool!r}")
            if risk not in GRANTABLE_RISKS:
                raise RuntimeError(
                    f"capability {capability} grants {tool!r} at risk {risk} -- "
                    "ambient work carries no write authority (D03)"
                )
            if tool.lower() in forbidden_lower:
                raise RuntimeError(f"capability {capability} grants forbidden tool {tool!r}")


_check_capability_table()


@dataclass(frozen=True, slots=True)
class SpeculativeGrant:
    """Le jeton de capacité remis à un travail. Une autorisation, jamais un ordre.

    `authorizes_actions` est un `ClassVar` fixé à faux, comme
    `PresentationContextSnapshot` (Slice 04) et `AmbientTrigger` (Slice 06) :
    aucune instance ne peut dire le contraire, pas même par
    `dataclasses.replace`.

    `origin` dit d'où vient la parole qui a déclenché le travail. Une origine
    `AMBIENT` ne change pas la table — elle ne peut pas l'élargir — mais elle
    est portée dans le jeton pour qu'un refus puisse le dire, et pour qu'un
    journal distingue une préparation née de la salle d'une préparation
    demandée par un tour explicite.
    """

    capabilities: tuple[SpeculativeCapability, ...]
    origin: UtteranceOrigin = UtteranceOrigin.AMBIENT

    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not isinstance(self.capabilities, tuple) or not self.capabilities:
            raise SpeculativeError(
                "speculative_grant_empty", "un travail spéculatif nomme au moins une capacité"
            )
        if len(self.capabilities) > len(SpeculativeCapability):
            raise SpeculativeError(
                "speculative_grant_too_many", "plus de capacités que l'énumération n'en contient"
            )
        for capability in self.capabilities:
            if not isinstance(capability, SpeculativeCapability):
                raise SpeculativeError(
                    "speculative_grant_invalid_capability",
                    "chaque capacité doit être une SpeculativeCapability",
                )
        if len(set(self.capabilities)) != len(self.capabilities):
            raise SpeculativeError(
                "speculative_grant_duplicate_capability", "une capacité nommée deux fois"
            )
        if not isinstance(self.origin, UtteranceOrigin):
            raise SpeculativeError(
                "speculative_grant_invalid_origin", "origin doit être un UtteranceOrigin"
            )

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        """Les outils accordés, triés, sans doublon. Calculé depuis la table."""

        granted: set[str] = set()
        for capability in self.capabilities:
            granted |= CAPABILITY_TOOLS[capability]
        return tuple(sorted(granted))

    def permits(self, tool_name: object) -> bool:
        """Vrai si l'outil est accordé. Liste d'autorisation, pas d'interdiction.

        Un nom inconnu, un nom vide, un objet qui n'est pas une chaîne : faux.
        Il n'y a pas de cas « on n'y avait pas pensé, donc on laisse passer ».
        """

        return isinstance(tool_name, str) and tool_name in self.allowed_tools

    def check(self, tool_name: object) -> None:
        """Lever un refus typé si l'outil n'est pas accordé.

        C'est le point de passage qu'un exécutant appelle avant d'employer un
        outil : `permits` répond, `check` refuse, et le refus porte l'origine
        pour que le journal dise *qui* a essayé.
        """

        if not self.permits(tool_name):
            raise SpeculativeError(
                "speculative_tool_not_granted",
                f"outil non accordé à un travail {self.origin.value} : {tool_name!r}",
            )


# --------------------------------------------------------------------------
# Priorités et budget
# --------------------------------------------------------------------------


class SpeculativePriority(IntEnum):
    """Rang d'un travail dans cette voie. Plus petit veut dire plus prioritaire.

    `P0_ADDRESSED_TURN` n'est **jamais admis** dans la réserve de cette voie :
    un tour adressé vit dans le cerveau, et ce module ne fait que lui garder de
    la place. Il existe dans l'énumération parce que la préemption a besoin de
    le nommer.

    `P1_EXPLICIT_PREPARATION` est une préparation demandée par un tour
    explicite : elle est admise, elle occupe la réserve, et elle préempte le
    spéculatif.

    `P2` à `P4` sont spéculatifs, donc sacrificiels (D08).
    """

    P0_ADDRESSED_TURN = 0
    P1_EXPLICIT_PREPARATION = 1
    P2_FACT_VERIFICATION = 2
    P3_REFERENCE_RESOLUTION = 3
    P4_TOPIC_EXPLORATION = 4


#: Les rangs explicites : protégés, jamais sacrifiés, servis par la réserve.
EXPLICIT_PRIORITIES: frozenset[SpeculativePriority] = frozenset(
    {SpeculativePriority.P0_ADDRESSED_TURN, SpeculativePriority.P1_EXPLICIT_PREPARATION}
)
#: Les rangs spéculatifs : sacrificiels, préemptables, plafonnés (D08).
SPECULATIVE_PRIORITIES: frozenset[SpeculativePriority] = (
    frozenset(SpeculativePriority) - EXPLICIT_PRIORITIES
)


#: Travaux simultanés que la voie tient au total, tous rangs confondus.
#: Huit sous-agents bornés, au-dessus des huit analyses que la voie ambiante
#: peut produire d'un coup (`DEFAULT_ANALYSIS_QUEUE`) et bien en dessous des 64
#: de `MAX_WORK_ITEMS` : la préparation n'est pas ce qui doit remplir l'état de
#: travail.
MAX_SPECULATIVE_POOL = 8
#: Places que **seul** un rang explicite peut prendre. Un bassin spéculatif
#: saturé laisse donc toujours deux places libres, et c'est la forme prise ici
#: par « l'interaction explicite a une priorité absolue » (D08).
RESERVED_EXPLICIT_SLOTS = 2


def max_speculative_jobs() -> int:
    """Plafond du spéculatif : le bassin moins la réserve explicite.

    Fonction plutôt que constante pour que le calcul soit lisible à un seul
    endroit et qu'un plafond négatif soit impossible à écrire.
    """

    return max(0, MAX_SPECULATIVE_POOL - RESERVED_EXPLICIT_SLOTS)


# --------------------------------------------------------------------------
# Clé de coalescence
# --------------------------------------------------------------------------

#: Longueur retenue d'une moitié de clé. Les identifiants de cette famille sont
#: bornés comme ceux de la Slice 04.
MAX_SPECULATIVE_JOB_KEY_CHARS = MAX_PRESENTATION_ID_CHARS


def job_key_text(value: object) -> str:
    """Normaliser un morceau de texte en clé de coalescence stable.

    Minuscules sans casse (`casefold`, qui traite « Écart » et « écart » ainsi
    que l'eszett allemand), espaces réduits à un seul, ponctuation de bord
    retirée, longueur bornée. Un texte qui ne donne rien rend la chaîne vide, et
    c'est `SpeculativeJobKey` qui décide si c'est acceptable.

    Le but n'est pas de comprendre la phrase : c'est de faire tomber deux
    formulations voisines de la même chose sur la même clé, pour que la voie
    ne prépare pas deux fois le même rapport. La Slice 06 prévient que
    `_references` rend une phrase entière ; la borne ci-dessous est donc ce qui
    empêche deux phrases longues et presque identiques de rater leur
    coalescence sur leur dernier mot.
    """

    if not isinstance(value, str):
        return ""
    collapsed = " ".join(value.split()).casefold()
    trimmed = collapsed.strip(" .,;:!?'\"()[]{}<>-–—…")
    return trimmed[:MAX_SPECULATIVE_JOB_KEY_CHARS]


@dataclass(frozen=True, slots=True)
class SpeculativeJobKey:
    """Identité d'un travail pour la déduplication : un sujet, une ressource.

    Deux déclencheurs qui portent le même sujet **et** la même ressource sont
    le même travail : le second rejoint le premier au lieu d'en lancer un
    autre. C'est la coalescence que `SLICE.md` demande « par sujet et clé de
    ressource », et elle est ici une valeur comparable plutôt qu'une
    comparaison éparpillée chez l'appelant.

    `resource_key` peut être vide : un sujet neuf ne cite aucune ressource. Un
    `topic_key` vide, en revanche, ne désigne rien — il est refusé.
    """

    topic_key: str
    resource_key: str = ""

    def __post_init__(self) -> None:
        for name, value in (("topic_key", self.topic_key), ("resource_key", self.resource_key)):
            if not isinstance(value, str):
                raise SpeculativeError(
                    "speculative_key_invalid", f"{name} doit être une chaîne"
                )
            if len(value) > MAX_SPECULATIVE_JOB_KEY_CHARS:
                raise SpeculativeError(
                    "speculative_key_too_long",
                    f"{name} dépasse {MAX_SPECULATIVE_JOB_KEY_CHARS} caractères",
                )
            if value != value.strip():
                raise SpeculativeError(
                    "speculative_key_untrimmed", f"{name} porte un espace de bord"
                )
        if not self.topic_key:
            raise SpeculativeError(
                "speculative_key_empty", "une clé de travail nomme toujours un sujet"
            )

    @property
    def value(self) -> str:
        """Forme plate de la clé. **Contient de la parole — jamais journalisée.**

        `resource_key` est dérivé du texte du déclencheur, et
        `docs/presentation-ambient-lane.md` §11 prévient que `_references` rend
        une **phrase entière** pour n'importe lequel de dix-neuf noms communs.
        Cette valeur porte donc ce qui a été dit dans la salle. Elle sert à
        comparer deux travaux en mémoire ; pour un journal, une ligne de trace
        ou un identifiant, c'est `digest` qu'il faut.
        """

        return f"{self.topic_key}|{self.resource_key}"

    @property
    def digest(self) -> str:
        """Empreinte courte et stable de la clé. Sans parole, donc journalisable.

        Deux travaux coalescés ont la même empreinte, ce qui suffit à suivre la
        déduplication dans une trace ; aucune phrase ne peut en être relue.
        """

        return sha256(self.value.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------
# Ce qu'une admission répond
# --------------------------------------------------------------------------


class SpeculativeAdmission(StrEnum):
    """Réponse typée d'une demande d'admission. Jamais une exception.

    Même discipline que le magasin de la Slice 04 : l'appelant reçoit une
    valeur qu'il peut compter, pas une exception qu'il pourrait avaler.
    """

    #: Le travail est admis et occupe une place.
    ACCEPTED = "accepted"
    #: Un travail de même clé était déjà là : celui-ci le rejoint.
    COALESCED = "coalesced"
    #: Le bassin est plein pour ce rang. Pour un rang spéculatif, cela veut
    #: dire que le plafond spéculatif est atteint, pas que la réserve l'est.
    CAPACITY = "capacity"
    #: La séance nommée n'est plus la séance courante.
    STALE_SESSION = "stale_session"
    #: La voie n'est pas ouverte : pas de séance, ou le mode n'est plus
    #: PRESENTATION.
    INACTIVE = "inactive"
    #: La demande n'est pas une demande légale (rang, capacité, clé).
    REJECTED = "rejected"


#: Ce qu'un déclencheur ambiant fait préparer : son rang, et les capacités qu'il
#: ouvre. Table close, lue par le service — l'aiguillage est une donnée, pas une
#: cascade de `if` chez l'appelant.
#:
#: Les clés sont les valeurs de `AmbientTriggerKind` (Slice 06), citées par leur
#: **chaîne** et non par l'énumération, pour que ce module reste sans
#: dépendance vers la voie ambiante : c'est ce qui laisse la fermeture d'import
#: de la Slice 06 intacte. Le service fait la jonction et refuse une nature
#: inconnue.
TRIGGER_PREPARATION: dict[str, tuple[SpeculativePriority, tuple[SpeculativeCapability, ...]]] = {
    "checkable_claim": (
        SpeculativePriority.P2_FACT_VERIFICATION,
        (SpeculativeCapability.FACT_VERIFICATION, SpeculativeCapability.RESEARCH_SEARCH),
    ),
    "external_reference": (
        SpeculativePriority.P3_REFERENCE_RESOLUTION,
        (SpeculativeCapability.DOCUMENT_RESOLUTION, SpeculativeCapability.RESEARCH_SEARCH),
    ),
    "open_question": (
        SpeculativePriority.P3_REFERENCE_RESOLUTION,
        (SpeculativeCapability.RESEARCH_SEARCH, SpeculativeCapability.WEB_NEWS_LOOKUP),
    ),
    "new_topic": (
        SpeculativePriority.P4_TOPIC_EXPLORATION,
        (SpeculativeCapability.RESEARCH_SEARCH,),
    ),
}
