"""Mémoire de séance du mode PRESENTATION : bornée, éphémère, jamais canonique.

Handoff `jarvis-presentation-interaction-mode`, Slice 04. Deux choses
**délibérément séparées** (Décision D06) vivent ici, plus l'instantané qui les
recolle :

- `PresentationWorkingSet` — ce que l'enrichissement a **committé** : sujets
  actifs, entités résolues, affirmations avec provenance, sources, ressources
  préparées avec leur température (`hot` / `warm` / `discardable`), questions
  ouvertes, points d'attention, et la fraîcheur de tout cela ;
- `PresentationTranscriptTail` — une petite fenêtre de parole **récente**, qui
  reste fraîche *indépendamment* de l'enrichissement. C'est elle qui fait qu'un
  « montre-moi ça » ne se résout pas contre une analyse vieille de trente
  secondes ;
- `PresentationContextSnapshot` — le couple des deux, pris d'un bloc, que la
  voie prioritaire lit à l'adresse explicite.

**Décision D13 : rien d'ici n'est de la mémoire à long terme.** L'ensemble est borné,
lié à une séance, et n'est jamais versé automatiquement dans la mémoire
canonique. Ce module n'importe donc aucun port de persistance, et le magasin
(`jarvis/core/presentation_working_set.py`) n'en reçoit aucun.

**L'audio brut n'entre jamais ici.** La règle existe déjà dans le dépôt
(`jarvis/audio/duplex.py`, `jarvis/runtime/realtime_audio.py` : « Raw audio is
memory-only and never persisted ») ; elle est tenue ici par construction, parce
que tous les champs de texte refusent autre chose qu'une `str` — un `bytes`
d'échantillons PCM ne peut pas être rangé dans un de ces enregistrements.

**Les ressources préparées sont des références typées, pas des charges utiles
exécutables.** `docs/02-architecture.md` est explicite : si un graphique a
besoin d'une représentation, c'est un descripteur structuré sûr, jamais du HTML
exécutable. La règle s'applique **aux seules références** — localisateur, titre
de source ou de ressource, chaînes d'un descripteur — et pas au texte venu de
la parole. Un orateur dit « la marge < 10 % » ; une affirmation, une étiquette,
une question ou un motif d'attention n'ont donc à passer que par la borne de
taille (`bounded_text`). Une référence, elle, passe par `safe_reference_text` :
`<` y est refusé, et un localisateur ne peut porter qu'un schéma de la liste
blanche `ALLOWED_LOCATOR_SCHEMES` — ce qui ferme `javascript:`, `vbscript:` et
toute la famille `data:` d'un coup plutôt qu'une forme à la fois.

## Bornes

Chaque collection porte une borne de **compte**, chaque texte une borne de
**taille**, et le magasin applique une borne d'**âge**. Toutes les valeurs sont
des constantes de module, comme `jarvis/domain/brain_context.py` et
`jarvis/domain/work_state.py` :

| Collection | Borne | Pourquoi ce nombre |
| --- | ---: | --- |
| sujets | 12 | même ordre que `MAX_BRAIN_WORK_ACTIVE` : au-delà d'une douzaine de sujets vivants, plus personne ne suit, ni l'orateur ni le cerveau |
| entités | 24 | deux entités par sujet vivant, en moyenne |
| affirmations | 24 | deux affirmations vérifiables par sujet vivant |
| sources | 12 | une source par affirmation réellement vérifiée |
| ressources préparées | 16 | le travail spéculatif est sacrificiel (D08) ; au-delà, on prépare plus qu'on ne montrera |
| questions ouvertes | 12 | une par sujet vivant |
| points d'attention | 8 | même borne que `MAX_BRAIN_WORK_ATTENTION` : ce qu'on peut signaler sans noyer |
| fil récent | 16 entrées / 4 000 car. | une reprise déictique remonte quelques phrases, pas un chapitre |

L'ordre d'éviction est **déterministe** : chaque enregistrement expose
`sort_key`, les collections sont rangées dans cet ordre, et l'éviction retire
toujours par la **tête**. Pour une ressource préparée, la température passe
avant l'ancienneté : on jette d'abord ce qui est `discardable`, puis ce qui est
`warm`, jamais une ressource `hot` avant les deux autres.

Les références entre enregistrements (`topic_id` sur une affirmation, sur une
ressource) sont **souples** : un sujet qui sort de l'ensemble n'efface pas les
faits appris sous lui, et l'instantané n'exige aucune intégrité référentielle.
La provenance, elle, n'est jamais perdue : elle est copiée dans chaque
enregistrement au moment où il est créé, et elle survit à l'éviction du fil
d'où elle vient.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import json
import math
import re
from typing import Any, ClassVar

from jarvis.domain._checks import check_text

# --------------------------------------------------------------------------
# Bornes de compte
# --------------------------------------------------------------------------

#: Sujets vivants. Au-delà, le plus anciennement mentionné tombe.
MAX_WORKING_SET_TOPICS = 12
#: Entités résolues (personnes, produits, chiffres nommés).
MAX_WORKING_SET_ENTITIES = 24
#: Affirmations/faits retenus, avec provenance.
MAX_WORKING_SET_CLAIMS = 24
#: Sources citées ou retrouvées.
MAX_WORKING_SET_SOURCES = 12
#: Ressources préparées (références, jamais des charges utiles).
MAX_PREPARED_RESOURCES = 16
#: Questions ouvertes / incertitudes.
MAX_OPEN_QUESTIONS = 12
#: Points d'attention en attente de signalement.
MAX_ATTENTION_ITEMS = 8
#: Sources citables par une affirmation ou un point d'attention.
MAX_PROVENANCE_SOURCES = 4

#: Entrées du fil récent. Une reprise déictique (« ça », « cette courbe »)
#: remonte quelques phrases ; seize est déjà généreux.
MAX_TAIL_ENTRIES = 16
#: Budget total du fil récent, tous textes confondus.
MAX_TAIL_CHARS = 4_000
#: Une énonciation isolée ; au-delà, l'appelant tronque avec `clip_text`.
MAX_TAIL_ENTRY_CHARS = 600

# --------------------------------------------------------------------------
# Bornes de taille
# --------------------------------------------------------------------------

#: Identifiants de ce module. Plus courts que `MAX_ID_CHARS` (128) du domaine :
#: ils sont fabriqués par le magasin ou par un producteur ambiant, jamais
#: recopiés d'un fournisseur, et ils pèsent dans la taille de l'instantané.
MAX_PRESENTATION_ID_CHARS = 64
MAX_TOPIC_LABEL_CHARS = 120
MAX_ENTITY_LABEL_CHARS = 96
MAX_ENTITY_KIND_CHARS = 32
#: Une affirmation est une phrase, pas un paragraphe : ce qui ne tient pas en
#: 320 caractères n'est pas une affirmation vérifiable.
MAX_CLAIM_CHARS = 320
MAX_QUESTION_CHARS = 200
MAX_SOURCE_TITLE_CHARS = 120
#: Localisateur d'une source ou d'une ressource : URL, chemin, identifiant de
#: document ou d'objet de scène.
MAX_REFERENCE_CHARS = 300
MAX_RESOURCE_TITLE_CHARS = 120
#: Descripteur structuré d'une ressource (série de graphique, en-têtes de
#: tableau). Forme JSON compacte, jamais du balisage.
MAX_DESCRIPTOR_CHARS = 600
MAX_DESCRIPTOR_KEYS = 16
MAX_DESCRIPTOR_ITEMS = 32
MAX_DESCRIPTOR_TEXT_CHARS = 120
MAX_ATTENTION_REASON_CHARS = 160

#: Plafond dur de l'instantané de l'ensemble de travail, forme JSON compacte.
#: Ce n'est **pas** un budget de prompt — celui-là appartient à la projection
#: du tour cerveau (Slice 10), comme `MAX_BRAIN_WORK_CONTEXT_CHARS` l'est pour
#: le travail. C'est la preuve que le produit « compte maximal × taille
#: maximale » reste fini et connu.
#:
#: La valeur est choisie **au-dessus du produit réel**, mesuré par
#: `test_le_plafond_de_caracteres_passe_au_dessus_de_l_ensemble_reellement_maximal`,
#: qui construit l'ensemble vraiment maximal : identifiants de 64 caractères
#: partout, `source_ids` pleins, descripteur maximal sur les seize ressources,
#: motif d'attention plein. Il mesure 92 265 caractères ; le plafond garde donc
#: une marge d'environ 30 %, assez pour qu'une correction de champ ne le fasse
#: pas basculer, trop peu pour qu'il cesse de vouloir dire quelque chose. La première version de cette borne (80 000) était
#: *sous* ce produit de près de moitié, et la phrase « la borne ne peut jamais
#: refuser un ensemble légal » était donc fausse, parce que le test qui la
#: soutenait construisait un ensemble seulement à moitié maximal.
#:
#: Et parce qu'une borne qu'on croit inatteignable est exactement celle qu'on
#: finira par atteindre, le magasin **ne laisse plus fuir** ce refus : il le
#: rend en `CAPACITY` typé (`presentation_working_set_too_large`), comme tous
#: ses autres refus.
MAX_WORKING_SET_CHARS = 120_000

# --------------------------------------------------------------------------
# Bornes d'âge (appliquées par le magasin, exprimées ici)
# --------------------------------------------------------------------------

#: Âge maximal d'une entrée du fil, mesuré depuis la parole la plus récente
#: connue (et non depuis une horloge murale) : trois minutes de discours.
MAX_TAIL_AGE_S = 180.0
#: Âge maximal d'un enregistrement de l'ensemble de travail depuis sa dernière
#: mention : une demi-heure, soit la durée d'une présentation ordinaire.
MAX_WORKING_SET_AGE_S = 1_800.0
#: Inactivité au-delà de laquelle une ressource préparée refroidit d'un cran.
MAX_RESOURCE_IDLE_S = 600.0


# `>` reste permis : « chiffre d'affaires > 10 M » est une étiquette de
# graphique légitime. `<` ouvre une balise, et n'a rien à faire dans une
# référence.
_MARKUP = re.compile(r"<")

# Un schéma est un préfixe d'**au moins deux** lettres suivi de `:` : une lettre
# seule est une unité de disque Windows (`C:\...`), pas un schéma.
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]+):")

#: Schémas admis dans le localisateur d'une source ou d'une ressource. Liste
#: **blanche**, et c'est le point : une liste noire ferme les formes qu'on a
#: pensé à écrire (`javascript:`, `data:text/html`) et laisse passer celles
#: qu'on a oubliées — `vbscript:`, `data:image/svg+xml` (un SVG est un porteur
#: de script dans un `<object>` ou une iframe). Les natures de ressource sont
#: closes, donc la liste des schémas qu'elles peuvent porter l'est aussi. Un
#: localisateur **sans** schéma (un chemin, un identifiant nu) reste admis.
ALLOWED_LOCATOR_SCHEMES = frozenset(
    {"http", "https", "file", "doc", "chart", "scene", "dataset", "note"}
)


class PresentationWorkingSetError(ValueError):
    """Refus typé, avec un code stable et un message lisible.

    Même forme que `InteractionModeError` (Slice 01) : le code est stable et
    ASCII pour qu'une surface puisse s'y brancher, le message est pour l'humain.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UtteranceOrigin(StrEnum):
    """D'où vient une parole. Une parole ambiante n'autorise rien (D03)."""

    AMBIENT = "ambient"
    ADDRESSED = "addressed"


class ResourceTemperature(StrEnum):
    """Chaleur d'une ressource préparée.

    `HOT` : liée à un sujet vivant et récemment utilisée — on la montrerait
    maintenant. `WARM` : préparée, encore pertinente, pas sollicitée.
    `DISCARDABLE` : son sujet a quitté l'ensemble, ou elle dort depuis
    `MAX_RESOURCE_IDLE_S`. C'est la première jetée.
    """

    HOT = "hot"
    WARM = "warm"
    DISCARDABLE = "discardable"

    @property
    def rank(self) -> int:
        """Rang d'éviction : 0 part en premier."""

        return _TEMPERATURE_RANK[self]


_TEMPERATURE_RANK = {
    ResourceTemperature.DISCARDABLE: 0,
    ResourceTemperature.WARM: 1,
    ResourceTemperature.HOT: 2,
}


class ResourceKind(StrEnum):
    """Nature d'une ressource préparée. Toutes sont des **références**.

    `SCENE_OBJECT` ne porte que l'identifiant d'un objet de scène déjà créé :
    l'autorité d'affichage reste à la scène (D12), ce module ne la double pas.
    `CHART_DESCRIPTOR` est la représentation sûre demandée par
    `docs/02-architecture.md` — des données, jamais du HTML.
    """

    DOCUMENT = "document"
    WEB_PAGE = "web_page"
    CHART_DESCRIPTOR = "chart_descriptor"
    SCENE_OBJECT = "scene_object"
    DATASET = "dataset"
    NOTE = "note"


class ClaimStatus(StrEnum):
    """Où en est la vérification d'une affirmation.

    `ASSERTED` : dite, pas vérifiée. `SUPPORTED` / `CONTRADICTED` : une source
    l'appuie ou la contredit. `UNCERTAIN` : vérifiée sans conclusion — ce qui
    n'est **pas** une contradiction, et c'est la distinction qui empêche une
    recherche ratée de devenir une alerte (`docs/03-implementation-strategy.md`).
    """

    ASSERTED = "asserted"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNCERTAIN = "uncertain"


class AttentionCategory(StrEnum):
    """Nature d'un point d'attention. Slice 09 en possède la présentation."""

    CONTRADICTION = "contradiction"
    MISMATCH = "mismatch"
    MISSING_SOURCE = "missing_source"
    STALE_RESOURCE = "stale_resource"


class AttentionSeverity(StrEnum):
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"


# --------------------------------------------------------------------------
# Contrôles partagés
# --------------------------------------------------------------------------


def presentation_id(name: str, value: object, *, required: bool = True) -> None:
    """Identifiant borné, non vide, sans espace autour, imprimable."""

    if value is None and not required:
        return
    check_text(name, value, MAX_PRESENTATION_ID_CHARS)
    text = str(value)
    if not text or text != text.strip():
        raise ValueError(f"{name} must be a non-empty identifier without surrounding spaces")


def bounded_text(name: str, value: object, limit: int, *, required: bool = True) -> None:
    """Texte public borné. Rien d'autre : c'est de la parole reformulée.

    `check_text` refuse déjà tout ce qui n'est pas une `str` : c'est par là
    qu'un tampon d'audio brut (`bytes`, `bytearray`, `memoryview`) est rejeté,
    et c'est pourquoi aucun champ de ce module n'a besoin d'une règle
    supplémentaire pour tenir la promesse « l'audio n'entre jamais ici ».

    **Aucune règle de balisage ici.** Une affirmation, une étiquette, une
    question, un motif d'attention viennent de ce qui a été dit dans la pièce ;
    « la marge < 10 % » est une phrase française ordinaire, et la refuser avec
    un code parlant d'une *ressource* donnait à la Slice 06 une exception là où
    elle attend une disposition typée.
    """

    check_text(name, value, limit, single_line=False)
    if required and not str(value).strip():
        raise ValueError(f"{name} is required")


def safe_reference_text(
    name: str, value: object, limit: int, *, required: bool = True, locator: bool = False
) -> None:
    """Texte d'une **référence** : borné, sans balisage, schéma sur liste blanche.

    Réservé au localisateur et au titre d'une source ou d'une ressource, et aux
    chaînes d'un descripteur. Ce sont les seules valeurs de ce module qu'une
    surface pourrait un jour suivre ou rendre.
    """

    bounded_text(name, value, limit, required=required)
    text = str(value)
    if _MARKUP.search(text):
        raise PresentationWorkingSetError(
            "presentation_resource_not_a_reference",
            f"{name} : une ressource préparée est une référence typée, jamais du balisage exécutable.",
        )
    if not locator:
        return
    found = _SCHEME.match(text)
    if found is not None and found.group(1).lower() not in ALLOWED_LOCATOR_SCHEMES:
        raise PresentationWorkingSetError(
            "presentation_resource_scheme_not_allowed",
            f"{name} : schéma « {found.group(1)[:16]} » hors de la liste blanche des références.",
        )


def _aware(name: str, value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _confidence(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{name} must be a finite confidence between 0 and 1")


#: La même règle, sous un nom public, à côté de `check_text` et
#: `check_descriptor`. La Slice 09 valide elle aussi une confiance : un second
#: contrôle écrit là-bas finirait par diverger de celui-ci, et deux bornes
#: pour un même nombre est exactement le genre de dérive que ce module
#: combat partout ailleurs.
check_confidence = _confidence


def _sequence(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _id_tuple(name: str, values: object, limit: int) -> None:
    if not isinstance(values, tuple) or len(values) > limit:
        raise ValueError(f"{name} must be a tuple of at most {limit} identifiers")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not repeat an identifier")
    for item in values:
        presentation_id(f"{name} entry", item)


def check_descriptor(name: str, value: object) -> None:
    """Descripteur structuré sûr : des données, jamais un programme.

    Autorisé : une table plate de clés courtes vers des scalaires, ou vers une
    liste bornée de scalaires (une série de graphique, une colonne). Rien de
    plus profond, rien de balisé, taille compacte bornée. C'est la « safe
    structured descriptor » de `docs/02-architecture.md`.
    """

    if value is None:
        return
    if not isinstance(value, dict):
        raise PresentationWorkingSetError(
            "presentation_resource_not_a_reference",
            f"{name} : le descripteur d'une ressource est une table de données bornée.",
        )
    if len(value) > MAX_DESCRIPTOR_KEYS:
        raise ValueError(f"{name} holds at most {MAX_DESCRIPTOR_KEYS} keys")
    for key, item in value.items():
        safe_reference_text(f"{name} key", key, MAX_DESCRIPTOR_TEXT_CHARS)
        entries = item if isinstance(item, (list, tuple)) else [item]
        if isinstance(item, (list, tuple)) and len(item) > MAX_DESCRIPTOR_ITEMS:
            raise ValueError(f"{name}[{key}] holds at most {MAX_DESCRIPTOR_ITEMS} values")
        for entry in entries:
            if isinstance(entry, str):
                safe_reference_text(f"{name}[{key}]", entry, MAX_DESCRIPTOR_TEXT_CHARS, required=False)
            elif isinstance(entry, bool) or entry is None:
                continue
            elif isinstance(entry, (int, float)):
                if not math.isfinite(float(entry)):
                    raise ValueError(f"{name}[{key}] must hold finite numbers")
            else:
                raise PresentationWorkingSetError(
                    "presentation_resource_not_a_reference",
                    f"{name}[{key}] : seuls des scalaires bornés sont admis dans un descripteur.",
                )
    if compact_chars(value) > MAX_DESCRIPTOR_CHARS:
        raise ValueError(f"{name} exceeds {MAX_DESCRIPTOR_CHARS} compact characters")


def compact_chars(payload: object) -> int:
    """Taille de la forme JSON compacte, comme `brain_context._compact_size`."""

    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservationProvenance:
    """D'où vient ce qu'on a retenu. Copiée dans chaque enregistrement.

    `sequence` est le rang de l'énonciation dans le fil récent au moment de
    l'observation. C'est **la** mesure de fraîcheur de l'ensemble de travail :
    la différence entre le plus haut `sequence` committé et le plus haut
    `sequence` du fil est exactement le retard de l'enrichissement (D06).

    La provenance survit à l'éviction de l'énonciation dont elle parle : le
    texte disparaît du fil, `utterance_id` et `sequence` restent, et une
    affirmation ne devient donc jamais orpheline.

    Elle ne cite **pas** de sources : une provenance dit d'où vient ce qu'on a
    entendu, une source dit ce qui l'appuie ou la contredit. Ce second lien
    existe une fois, sur `PresentationClaim.source_ids`, et une fois seulement.
    """

    utterance_id: str
    sequence: int
    observed_at: datetime
    origin: UtteranceOrigin = UtteranceOrigin.AMBIENT

    def __post_init__(self) -> None:
        presentation_id("utterance_id", self.utterance_id)
        _sequence("sequence", self.sequence)
        _aware("observed_at", self.observed_at)
        if not isinstance(self.origin, UtteranceOrigin):
            raise TypeError("origin must be an UtteranceOrigin")

    def to_payload(self) -> dict[str, Any]:
        return {
            "utterance_id": self.utterance_id,
            "sequence": self.sequence,
            "observed_at": self.observed_at.isoformat(),
            "origin": self.origin.value,
        }


# --------------------------------------------------------------------------
# Enregistrements
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PresentationTopic:
    """Un sujet vivant. `mention_count` est ce que la coalescence fait monter."""

    topic_id: str
    label: str
    provenance: ObservationProvenance
    first_seen_at: datetime
    last_seen_at: datetime
    mention_count: int = 1

    def __post_init__(self) -> None:
        presentation_id("topic_id", self.topic_id)
        bounded_text("topic label", self.label, MAX_TOPIC_LABEL_CHARS)
        _provenance(self.provenance)
        _span(self.first_seen_at, self.last_seen_at, self.provenance)
        if isinstance(self.mention_count, bool) or not isinstance(self.mention_count, int) or self.mention_count < 1:
            raise ValueError("mention_count must be a positive integer")

    @property
    def record_id(self) -> str:
        return self.topic_id

    @property
    def sort_key(self) -> tuple:
        return (self.last_seen_at, self.topic_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "label": self.label,
            "provenance": self.provenance.to_payload(),
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "mention_count": self.mention_count,
        }


@dataclass(frozen=True, slots=True)
class PresentationEntity:
    """Une entité résolue : personne, produit, chiffre nommé."""

    entity_id: str
    label: str
    kind: str
    provenance: ObservationProvenance
    first_seen_at: datetime
    last_seen_at: datetime
    topic_id: str | None = None

    def __post_init__(self) -> None:
        presentation_id("entity_id", self.entity_id)
        bounded_text("entity label", self.label, MAX_ENTITY_LABEL_CHARS)
        bounded_text("entity kind", self.kind, MAX_ENTITY_KIND_CHARS)
        _provenance(self.provenance)
        _span(self.first_seen_at, self.last_seen_at, self.provenance)
        presentation_id("topic_id", self.topic_id, required=False)

    @property
    def record_id(self) -> str:
        return self.entity_id

    @property
    def sort_key(self) -> tuple:
        return (self.last_seen_at, self.entity_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "label": self.label,
            "kind": self.kind,
            "provenance": self.provenance.to_payload(),
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "topic_id": self.topic_id,
        }


@dataclass(frozen=True, slots=True)
class PresentationClaim:
    """Une affirmation entendue, avec sa provenance et son état de vérification.

    Le `statement` est une **reformulation bornée** produite par l'analyse, pas
    une transcription : le fil récent est le seul endroit où de la parole
    littérale est conservée, et il a sa propre durée de vie, bien plus courte.
    """

    claim_id: str
    statement: str
    provenance: ObservationProvenance
    first_seen_at: datetime
    last_seen_at: datetime
    status: ClaimStatus = ClaimStatus.ASSERTED
    confidence: float = 0.0
    topic_id: str | None = None
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        presentation_id("claim_id", self.claim_id)
        bounded_text("claim statement", self.statement, MAX_CLAIM_CHARS)
        _provenance(self.provenance)
        _span(self.first_seen_at, self.last_seen_at, self.provenance)
        if not isinstance(self.status, ClaimStatus):
            raise TypeError("status must be a ClaimStatus")
        _confidence("confidence", self.confidence)
        presentation_id("topic_id", self.topic_id, required=False)
        _id_tuple("source_ids", self.source_ids, MAX_PROVENANCE_SOURCES)

    @property
    def record_id(self) -> str:
        return self.claim_id

    @property
    def sort_key(self) -> tuple:
        return (self.last_seen_at, self.claim_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "provenance": self.provenance.to_payload(),
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "status": self.status.value,
            "confidence": float(self.confidence),
            "topic_id": self.topic_id,
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True, slots=True)
class PresentationSource:
    """Une source retrouvée : une référence, un titre, une date de lecture."""

    source_id: str
    kind: ResourceKind
    reference: str
    title: str
    retrieved_at: datetime

    def __post_init__(self) -> None:
        presentation_id("source_id", self.source_id)
        if not isinstance(self.kind, ResourceKind):
            raise TypeError("kind must be a ResourceKind")
        safe_reference_text("source reference", self.reference, MAX_REFERENCE_CHARS, locator=True)
        safe_reference_text("source title", self.title, MAX_SOURCE_TITLE_CHARS, required=False)
        _aware("retrieved_at", self.retrieved_at)

    @property
    def record_id(self) -> str:
        return self.source_id

    @property
    def sort_key(self) -> tuple:
        return (self.retrieved_at, self.source_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "kind": self.kind.value,
            "reference": self.reference,
            "title": self.title,
            "retrieved_at": self.retrieved_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ResourceReference:
    """Référence typée vers quelque chose de préparé. Jamais un exécutable.

    `locator` est une URL, un chemin, un identifiant de document ou d'objet de
    scène. `descriptor` est la seule représentation admise pour un contenu qui
    n'existe nulle part ailleurs (les séries d'un graphique) : une table de
    données bornée, validée par `check_descriptor`.
    """

    kind: ResourceKind
    locator: str
    title: str = ""
    descriptor: dict[str, Any] | None = field(default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ResourceKind):
            raise TypeError("kind must be a ResourceKind")
        safe_reference_text("resource locator", self.locator, MAX_REFERENCE_CHARS, locator=True)
        safe_reference_text("resource title", self.title, MAX_RESOURCE_TITLE_CHARS, required=False)
        check_descriptor("resource descriptor", self.descriptor)

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "locator": self.locator,
            "title": self.title,
            "descriptor": None if self.descriptor is None else dict(self.descriptor),
        }


@dataclass(frozen=True, slots=True)
class PreparedResource:
    """Ce qui a été préparé d'avance, et à quel point il est encore chaud."""

    resource_id: str
    reference: ResourceReference
    provenance: ObservationProvenance
    prepared_at: datetime
    last_used_at: datetime
    temperature: ResourceTemperature = ResourceTemperature.WARM
    topic_id: str | None = None
    claim_id: str | None = None

    def __post_init__(self) -> None:
        presentation_id("resource_id", self.resource_id)
        if not isinstance(self.reference, ResourceReference):
            raise TypeError("reference must be a ResourceReference")
        _provenance(self.provenance)
        _span(self.prepared_at, self.last_used_at, self.provenance)
        if not isinstance(self.temperature, ResourceTemperature):
            raise TypeError("temperature must be a ResourceTemperature")
        presentation_id("topic_id", self.topic_id, required=False)
        presentation_id("claim_id", self.claim_id, required=False)

    @property
    def record_id(self) -> str:
        return self.resource_id

    @property
    def sort_key(self) -> tuple:
        # La température passe avant l'ancienneté : on jette d'abord ce qui est
        # jetable, puis ce qui est tiède, et une ressource chaude ne part
        # jamais avant les deux autres.
        return (self.temperature.rank, self.last_used_at, self.resource_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "reference": self.reference.to_payload(),
            "provenance": self.provenance.to_payload(),
            "prepared_at": self.prepared_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat(),
            "temperature": self.temperature.value,
            "topic_id": self.topic_id,
            "claim_id": self.claim_id,
        }


@dataclass(frozen=True, slots=True)
class OpenQuestion:
    """Une incertitude explicite : ce que la séance n'a pas résolu."""

    question_id: str
    text: str
    provenance: ObservationProvenance
    asked_at: datetime
    topic_id: str | None = None

    def __post_init__(self) -> None:
        presentation_id("question_id", self.question_id)
        bounded_text("question text", self.text, MAX_QUESTION_CHARS)
        _provenance(self.provenance)
        _aware("asked_at", self.asked_at)
        presentation_id("topic_id", self.topic_id, required=False)

    @property
    def record_id(self) -> str:
        return self.question_id

    @property
    def sort_key(self) -> tuple:
        return (self.asked_at, self.question_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "text": self.text,
            "provenance": self.provenance.to_payload(),
            "asked_at": self.asked_at.isoformat(),
            "topic_id": self.topic_id,
        }


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """Un point qui mérite un signal discret (D11). Slice 09 le présente."""

    attention_id: str
    category: AttentionCategory
    severity: AttentionSeverity
    confidence: float
    raised_at: datetime
    reason: str = ""
    claim_id: str | None = None
    topic_id: str | None = None
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        presentation_id("attention_id", self.attention_id)
        if not isinstance(self.category, AttentionCategory):
            raise TypeError("category must be an AttentionCategory")
        if not isinstance(self.severity, AttentionSeverity):
            raise TypeError("severity must be an AttentionSeverity")
        _confidence("confidence", self.confidence)
        _aware("raised_at", self.raised_at)
        bounded_text("attention reason", self.reason, MAX_ATTENTION_REASON_CHARS, required=False)
        presentation_id("claim_id", self.claim_id, required=False)
        presentation_id("topic_id", self.topic_id, required=False)
        _id_tuple("source_ids", self.source_ids, MAX_PROVENANCE_SOURCES)

    @property
    def record_id(self) -> str:
        return self.attention_id

    @property
    def sort_key(self) -> tuple:
        return (self.raised_at, self.attention_id)

    #: Clé de coalescence : deux fois la même contradiction sur la même
    #: affirmation est un seul point d'attention, pas deux sons (D11).
    @property
    def dedup_key(self) -> tuple:
        return (self.category, self.claim_id, self.topic_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "attention_id": self.attention_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "confidence": float(self.confidence),
            "raised_at": self.raised_at.isoformat(),
            "reason": self.reason,
            "claim_id": self.claim_id,
            "topic_id": self.topic_id,
            "source_ids": list(self.source_ids),
        }


def _provenance(value: object) -> None:
    if not isinstance(value, ObservationProvenance):
        raise TypeError("provenance must be an ObservationProvenance")


def _span(first: object, last: object, provenance: object = None) -> None:
    """Un enregistrement va de sa première vue à sa dernière, dans cet ordre.

    Et il ne peut pas avoir été *observé* après avoir été vu pour la dernière
    fois. Sans cette troisième borne, un enregistrement pouvait porter une
    provenance d'aujourd'hui et une récence d'il y a une heure : le magasin
    avançait son horloge sur la provenance, puis jugeait le même
    enregistrement trop vieux sur sa récence. Une forme que rien ne peut
    produire honnêtement est refusée à la porte plutôt que gérée en aval.
    """

    _aware("first timestamp", first)
    _aware("last timestamp", last)
    if last < first:  # type: ignore[operator]
        raise ValueError("a record cannot be last seen before it was first seen")
    if provenance is not None and provenance.observed_at > last:  # type: ignore[union-attr,operator]
        raise ValueError("a record cannot be observed after it was last seen")


#: Les sept natures d'enregistrement que l'ensemble de travail retient.
PRESENTATION_RECORD_TYPES: tuple[type, ...] = (
    PresentationTopic,
    PresentationEntity,
    PresentationClaim,
    PresentationSource,
    PreparedResource,
    OpenQuestion,
    AttentionItem,
)

#: Nom de collection par nature d'enregistrement, avec sa borne de compte.
RECORD_COLLECTIONS: dict[type, tuple[str, int]] = {
    PresentationTopic: ("topics", MAX_WORKING_SET_TOPICS),
    PresentationEntity: ("entities", MAX_WORKING_SET_ENTITIES),
    PresentationClaim: ("claims", MAX_WORKING_SET_CLAIMS),
    PresentationSource: ("sources", MAX_WORKING_SET_SOURCES),
    PreparedResource: ("resources", MAX_PREPARED_RESOURCES),
    OpenQuestion: ("questions", MAX_OPEN_QUESTIONS),
    AttentionItem: ("attention", MAX_ATTENTION_ITEMS),
}


# --------------------------------------------------------------------------
# Le fil récent
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TranscriptTailEntry:
    """Une énonciation récente, telle qu'elle a été entendue.

    `sequence` est attribué par le magasin et ne bouge plus : une révision de
    transcription garde son rang, sinon une correction tardive se ferait passer
    pour la parole la plus fraîche. `revision` monte, et une révision plus
    ancienne que celle détenue est refusée.
    """

    utterance_id: str
    sequence: int
    text: str
    spoken_at: datetime
    origin: UtteranceOrigin = UtteranceOrigin.AMBIENT
    revision: int = 0

    def __post_init__(self) -> None:
        presentation_id("utterance_id", self.utterance_id)
        _sequence("sequence", self.sequence)
        # Le texte du fil est de la parole : il peut contenir n'importe quel
        # caractère imprimable, y compris `<`. Il n'est **jamais** une
        # référence, donc `safe_reference_text` ne s'applique pas ici ; seule la
        # borne de taille et le refus de tout ce qui n'est pas une `str`
        # comptent — c'est ce dernier qui interdit l'audio brut.
        check_text("tail text", self.text, MAX_TAIL_ENTRY_CHARS, single_line=False)
        _aware("spoken_at", self.spoken_at)
        if not isinstance(self.origin, UtteranceOrigin):
            raise TypeError("origin must be an UtteranceOrigin")
        _sequence("revision", self.revision)

    @property
    def sort_key(self) -> tuple:
        """Ordre d'éviction du fil : le rang, et rien d'autre.

        Pas la date de parole : deux énonciations peuvent porter le même
        horodatage, et c'est l'ordre d'arrivée qui décide laquelle est « la
        dernière ». Le rang est unique dans une séance, donc total.
        """

        return (self.sequence,)

    def to_payload(self) -> dict[str, Any]:
        return {
            "utterance_id": self.utterance_id,
            "sequence": self.sequence,
            "text": self.text,
            "spoken_at": self.spoken_at.isoformat(),
            "origin": self.origin.value,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class PresentationTranscriptTail:
    """La fenêtre de parole récente. Bornée en compte, en taille et en âge.

    **Elle ne dépend pas de l'enrichissement.** C'est toute la raison de son
    existence : une analyse ambiante peut prendre des secondes, et pendant ce
    temps un « montre-moi ça » doit se résoudre contre ce qui vient d'être dit,
    pas contre le dernier fait committé (D06).

    Ce n'est **pas** `selected_voice_context`
    (`jarvis/runtime/conversation_context.py`) : celui-là projette les derniers
    tours *committés* d'une conversation pour construire un contexte de
    fournisseur, il vit aussi longtemps que la conversation, et il ne connaît
    que de la parole adressée. Celui-ci retient de la parole ambiante,
    révisable, non committée, pour la durée d'une séance seulement.
    """

    entries: tuple[TranscriptTailEntry, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple) or any(
            not isinstance(item, TranscriptTailEntry) for item in self.entries
        ):
            raise TypeError("tail entries must be a tuple of TranscriptTailEntry")
        if len(self.entries) > MAX_TAIL_ENTRIES:
            raise ValueError(f"tail holds at most {MAX_TAIL_ENTRIES} entries")
        ids = [item.utterance_id for item in self.entries]
        if len(set(ids)) != len(ids):
            raise ValueError("tail must not hold the same utterance twice")
        sequences = [item.sequence for item in self.entries]
        if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
            raise ValueError("tail entries must be strictly ordered by sequence")
        if self.text_chars > MAX_TAIL_CHARS:
            raise ValueError(f"tail exceeds {MAX_TAIL_CHARS} characters")

    @property
    def text_chars(self) -> int:
        return sum(len(item.text) for item in self.entries)

    @property
    def latest(self) -> TranscriptTailEntry | None:
        """La parole la plus récente. C'est elle que résout un déictique."""

        return self.entries[-1] if self.entries else None

    @property
    def latest_sequence(self) -> int:
        """Rang de la parole la plus récente ; 0 si le fil est vide."""

        return self.entries[-1].sequence if self.entries else 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "entries": [item.to_payload() for item in self.entries],
            "count": len(self.entries),
            "text_chars": self.text_chars,
            "latest_sequence": self.latest_sequence,
        }


# --------------------------------------------------------------------------
# L'ensemble de travail et l'instantané
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PresentationWorkingSet:
    """L'état committé : ce que l'enrichissement a compris, borné.

    `observed_sequence` est le plus haut rang d'énonciation qu'un
    enregistrement de cet ensemble cite. Comparé à `latest_sequence` du fil, il
    donne le retard de l'enrichissement sans qu'aucun producteur n'ait à le
    déclarer.
    """

    topics: tuple[PresentationTopic, ...] = ()
    entities: tuple[PresentationEntity, ...] = ()
    claims: tuple[PresentationClaim, ...] = ()
    sources: tuple[PresentationSource, ...] = ()
    resources: tuple[PreparedResource, ...] = ()
    questions: tuple[OpenQuestion, ...] = ()
    attention: tuple[AttentionItem, ...] = ()
    observed_sequence: int = 0
    #: Quand le magasin a committé pour la dernière fois, quelle qu'en soit la
    #: nature. Sert à faire avancer l'horloge des bornes d'âge, **jamais** à
    #: mesurer la fraîcheur : `observed_sequence` est la seule mesure de ce que
    #: l'analyse a réellement rattrapé.
    committed_at: datetime | None = None

    def __post_init__(self) -> None:
        for name, cls in (
            ("topics", PresentationTopic),
            ("entities", PresentationEntity),
            ("claims", PresentationClaim),
            ("sources", PresentationSource),
            ("resources", PreparedResource),
            ("questions", OpenQuestion),
            ("attention", AttentionItem),
        ):
            values = getattr(self, name)
            limit = RECORD_COLLECTIONS[cls][1]
            if not isinstance(values, tuple) or any(not isinstance(item, cls) for item in values):
                raise TypeError(f"{name} must be a tuple of {cls.__name__}")
            if len(values) > limit:
                raise ValueError(f"{name} holds at most {limit} records")
            ids = [item.record_id for item in values]
            if len(set(ids)) != len(ids):
                raise ValueError(f"{name} must not hold the same identity twice")
            keys = [item.sort_key for item in values]
            if keys != sorted(keys):
                raise ValueError(f"{name} must be kept in eviction order")
        _sequence("observed_sequence", self.observed_sequence)
        if self.committed_at is not None:
            _aware("committed_at", self.committed_at)
        if self.payload_chars > MAX_WORKING_SET_CHARS:
            raise ValueError(f"working set exceeds {MAX_WORKING_SET_CHARS} compact characters")

    @property
    def payload_chars(self) -> int:
        return compact_chars(self.to_payload())

    def counts(self) -> dict[str, int]:
        """Comptes par collection : ce qu'un journal a le droit de dire."""

        return {
            name: len(getattr(self, name))
            for name, _ in (RECORD_COLLECTIONS[cls] for cls in PRESENTATION_RECORD_TYPES)
        }

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            name: [item.to_payload() for item in getattr(self, name)]
            for name, _ in (RECORD_COLLECTIONS[cls] for cls in PRESENTATION_RECORD_TYPES)
        }
        payload["observed_sequence"] = self.observed_sequence
        payload["committed_at"] = None if self.committed_at is None else self.committed_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class PresentationContextSnapshot:
    """Le couple pris d'un bloc : état committé **et** parole fraîche (D06).

    C'est ce que la voie prioritaire lit au moment de l'adresse explicite. Les
    deux moitiés viennent forcément du même instant, parce que le magasin ne
    publie jamais l'une sans l'autre : il remplace **une seule** référence.

    `authorizes_actions` est faux et ne se règle pas : un instantané de séance
    est du contexte, jamais un ordre (D03), exactement comme
    `VoiceConversationSnapshot`.
    """

    session_id: str | None
    generation: int
    revision: int
    as_of: datetime
    working_set: PresentationWorkingSet = field(default_factory=PresentationWorkingSet)
    tail: PresentationTranscriptTail = field(default_factory=PresentationTranscriptTail)
    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        presentation_id("session_id", self.session_id, required=False)
        _sequence("generation", self.generation)
        _sequence("revision", self.revision)
        _aware("as_of", self.as_of)
        if not isinstance(self.working_set, PresentationWorkingSet):
            raise TypeError("working_set must be a PresentationWorkingSet")
        if not isinstance(self.tail, PresentationTranscriptTail):
            raise TypeError("tail must be a PresentationTranscriptTail")

    @property
    def active(self) -> bool:
        """Vrai quand une séance est liée. Faux dès qu'elle est retirée."""

        return self.session_id is not None

    @property
    def enrichment_lag_entries(self) -> int:
        """Énonciations du fil qu'aucun enregistrement committé ne cite encore.

        Zéro : l'analyse a rattrapé la parole. Positif : elle est en retard, et
        c'est précisément pour ces énonciations-là que le fil existe.
        """

        floor = self.working_set.observed_sequence
        return sum(1 for item in self.tail.entries if item.sequence > floor)

    @property
    def enrichment_lag_s(self) -> float:
        """Secondes de **parole non encore enrichie**. 0.0 seulement si rattrapé.

        Mesurée entre la dernière énonciation que l'ensemble de travail cite et
        la plus récente du fil : c'est littéralement la tranche de discours sur
        laquelle l'analyse n'a rien à dire. Quand elle n'a *jamais* rien dit
        (`observed_sequence == 0`), le plancher est la plus ancienne
        énonciation encore au fil, donc un magasin jamais enrichi rend le
        retard maximal, pas zéro.

        Elle ne se déduit **pas** de `committed_at`. C'était la première
        version, et elle mentait deux fois : un magasin jamais enrichi rendait
        `0.0`, indiscernable d'un magasin à jour, et le moindre enregistrement
        sans provenance — une source, un point d'attention, qui n'avancent
        volontairement pas `observed_sequence` — remettait le retard à zéro
        sans que l'analyse ait rattrapé une seule phrase. C'est exactement la
        lecture sur laquelle une Slice 08/10 conditionnerait un déictique.
        """

        floor = self.working_set.observed_sequence
        late = [item for item in self.tail.entries if item.sequence > floor]
        if not late:
            return 0.0
        enriched = [item for item in self.tail.entries if item.sequence <= floor]
        since = enriched[-1].spoken_at if enriched else late[0].spoken_at
        return max(0.0, (late[-1].spoken_at - since).total_seconds())

    def counts(self) -> dict[str, int]:
        """Résumé purement numérique, sûr pour un journal."""

        return {
            **self.working_set.counts(),
            "tail_entries": len(self.tail.entries),
            "tail_chars": self.tail.text_chars,
            "enrichment_lag_entries": self.enrichment_lag_entries,
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "generation": self.generation,
            "revision": self.revision,
            "as_of": self.as_of.isoformat(),
            "active": self.active,
            "authorizes_actions": self.authorizes_actions,
            "working_set": self.working_set.to_payload(),
            "tail": self.tail.to_payload(),
            "enrichment_lag_entries": self.enrichment_lag_entries,
        }


@dataclass(frozen=True, slots=True)
class PresentationObservation:
    """Une chose comprise, remise au magasin. Une seule porte d'entrée.

    `observation_id` est la clé de déduplication : un producteur ambiant qui
    rejoue son lot (Slice 06) ne doit pas faire monter deux fois le compte de
    mentions d'un sujet. `session_id` est la garde de séance : une observation
    d'une séance retirée est écartée, jamais appliquée à la suivante.
    """

    observation_id: str
    session_id: str
    record: Any

    def __post_init__(self) -> None:
        presentation_id("observation_id", self.observation_id)
        presentation_id("session_id", self.session_id)
        if not isinstance(self.record, PRESENTATION_RECORD_TYPES):
            raise TypeError("record must be one of the presentation record types")

    @property
    def collection(self) -> str:
        return RECORD_COLLECTIONS[type(self.record)][0]


# --------------------------------------------------------------------------
# Règles d'éviction pures
# --------------------------------------------------------------------------


def in_eviction_order(records: tuple) -> tuple:
    """Ranger une collection : la tête est toujours la prochaine évincée."""

    return tuple(sorted(records, key=lambda item: item.sort_key))


def evict_to_limit(records: tuple, limit: int) -> tuple[tuple, tuple]:
    """Ramener une collection sous sa borne, par la tête. Rendu `(gardés, jetés)`.

    Déterministe : l'ordre vient de `sort_key`, qui se termine toujours par
    l'identifiant, donc deux enregistrements de même date ne peuvent pas
    s'échanger d'une exécution à l'autre.
    """

    if limit < 0:
        raise ValueError("limit must not be negative")
    ordered = in_eviction_order(records)
    if len(ordered) <= limit:
        return ordered, ()
    cut = len(ordered) - limit
    return ordered[cut:], ordered[:cut]


def prune_by_age(records: tuple, *, now: datetime, max_age_s: float, stamp) -> tuple[tuple, tuple]:
    """Retirer ce qui est plus vieux que `max_age_s`, mesuré depuis `now`.

    `stamp` dit quelle date d'un enregistrement fait foi. Rendu `(gardés, jetés)`,
    les gardés en ordre d'éviction.
    """

    if max_age_s <= 0:
        raise ValueError("max_age_s must be positive")
    kept, dropped = [], []
    for item in in_eviction_order(records):
        age = (now - stamp(item)).total_seconds()
        (dropped if age > max_age_s else kept).append(item)
    return tuple(kept), tuple(dropped)


def derived_temperature(
    resource: PreparedResource, *, now: datetime, topic_ids: frozenset[str]
) -> ResourceTemperature:
    """Température **effective** d'une ressource, calculée, jamais accumulée.

    Trois règles, dans cet ordre, et rien d'autre :

    1. sa raison d'être a quitté l'ensemble (son sujet n'y est plus) : elle est
       `discardable`, quoi qu'on ait déclaré ;
    2. elle dort depuis plus de `MAX_RESOURCE_IDLE_S` : `discardable` ;
    3. sinon, la température déclarée fait foi — `hot` juste après une
       utilisation (`use_resource`), `warm` à la préparation.

    Calculer plutôt que refroidir par paliers rend la valeur indépendante du
    nombre de fois où le magasin a été sollicité entre deux instants : deux
    séances identiques donnent la même température, toujours.
    """

    if resource.topic_id is not None and resource.topic_id not in topic_ids:
        return ResourceTemperature.DISCARDABLE
    if (now - resource.last_used_at).total_seconds() > MAX_RESOURCE_IDLE_S:
        return ResourceTemperature.DISCARDABLE
    return resource.temperature
