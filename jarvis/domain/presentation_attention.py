"""L'événement d'attention de Presentation. Typé, gardé, et muet par construction.

Slice 09. D11 est verrouillée : *« une contradiction/incohérence significative
crée un petit signal sonore et un avertissement flottant. Jarvis n'explique pas
spontanément à voix haute. »* Ce module tient la première moitié de cette
phrase — **ce qui a le droit de devenir une alerte** — et rend structurellement
impossible la seconde moitié.

## Ce qui est repris, et ce qui est ajouté

La Slice 04 a déjà déclaré le vocabulaire (`AttentionCategory`,
`AttentionSeverity`) et l'enregistrement rangé dans l'ensemble de travail
(`AttentionItem`, avec sa clé de coalescence `(catégorie, affirmation, sujet)`).
Rien de tout cela n'est redéclaré ici : le LOG du handoff demande à cette Slice
d'**étendre** ce vocabulaire, pas d'en poser un second.

Ce que cette Slice ajoute, parce que `docs/02-architecture.md` le demande et que
la Slice 04 ne l'avait pas :

- `FactCheckAssessment` — ce qu'un exécutant de vérification **rend**. Un
  verdict, des pièces, une confiance, et le fait de savoir si la recherche a
  seulement abouti ;
- `AttentionEvidence` — une pièce à conviction, c'est-à-dire une **référence**
  (identifiant de source, locator, titre), jamais une charge utile ;
- `PresentationAttention` — l'événement typé nommé par l'architecture :
  catégorie, gravité, confiance, références de sources, affirmation et sujet
  liés, et références de ressources préparées. `AttentionItem` n'a pas ces
  dernières — elles avaient été retirées comme mortes en Slice 04 — et c'est
  exactement la différence entre *ce qui est rangé* et *ce qui est signalé* ;
- `decide_attention` — la porte. Une fonction pure, qui rend une décision
  typée et ne lève jamais.

## Pourquoi l'exécutant ne nomme ni sa catégorie ni sa gravité

C'est la leçon de la Slice 07, reprise telle quelle : *une affirmation ne peut
pas se déclarer question sans cesser d'en être une*. Un exécutant qui
choisirait lui-même `category=CONTRADICTION` transformerait un plafond en champ
de formulaire. Ici, la catégorie est **calculée** depuis le verdict par
`ALERTING_VERDICTS`, une table close, et la gravité depuis la confiance par
`severity_for`. Un exécutant ne peut donc écrire ni l'une ni l'autre.

## Un échec de recherche n'est pas une contradiction

C'est la contrainte la plus explicite de la Slice, et elle a deux moitiés, parce
qu'un exécutant peut se tromper dans les deux sens :

1. `searched=False` — la recherche n'a pas abouti. Refusé avant même de
   regarder le verdict, donc un exécutant qui rendrait `CONTRADICTED` sur une
   recherche ratée est refusé sous `attention_search_failed` et non promu ;
2. `ClaimStatus.UNCERTAIN` — la recherche a abouti sans conclure. La Slice 04
   avait déjà écrit pourquoi cette valeur existe : *« ce qui n'est pas une
   contradiction, et c'est la distinction qui empêche une recherche ratée de
   devenir une alerte »*. `ALERTING_VERDICTS` ne la contient pas, et
   `_check_alerting_table()` le vérifie à l'import.

## D11 : rien ici ne peut demander la parole

`PresentationAttention` ne porte **aucun** champ de parole : ni texte à dire,
ni nature de parole, ni disposition de sortie. Deux `ClassVar` le disent à voix
haute — `authorizes_actions` et `requests_speech`, tous deux `False` et
inaccessibles à `dataclasses.replace`, sur le modèle exact de
`SpeculativeGrant` et `PresentationContextSnapshot`. La preuve vivante est
ailleurs et elle est meilleure : la ligne `fact_check_attention` de
`PRESENTATION_OUTPUT_POLICY` porte `requires_explicit_address=False` et aucune
`safety_speech_kinds`, donc `may_speak` y est faux pour **toute** nature de
parole. Ce module s'y branche par `attention_output_policy()` plutôt que de
réaffirmer la règle dans ses propres mots.

## La parole ne descend pas dans la trace

`reason` est du texte issu de ce qui a été dit dans la salle : la Slice 04 le
valide avec `bounded_text` et non `safe_reference_text`, précisément parce que
« la marge < 10 % » est une phrase française ordinaire. Il est gardé dans
l'ensemble de travail, en mémoire, pour le tour adressé de la Slice 10 — c'est
littéralement le scénario de `HV-PRES-ALERT-01` : *« puis éventuellement
demander à Jarvis ce qu'il a trouvé »*.

Il ne descend **pas** dans `to_trace_payload()`. La trace est un fichier
durable, partagé par les trois processus, et les Slices 04, 06 et 08 ont toutes
posé la même règle : des identifiants, des nombres, des codes, jamais de la
parole. L'avertissement flottant est donc composé dans le navigateur à partir
de données typées — catégorie, bande de confiance, titres de sources — et non
d'une phrase recopiée. Tout ce qui traverse est validé par
`safe_reference_text`, la règle des locators et des titres.

## Les confiances ne sont pas étalonnées

`docs/presentation-ambient-lane.md` §11 le dit : les quatre confiances de
déclenchement sont codées en dur et non étalonnées. `MIN_ATTENTION_CONFIDENCE`
et `HIGH_CONFIDENCE` sont donc des **seuils de prudence**, pas des mesures, et
`confidence_band()` existe pour que la surface montre une bande et jamais un
nombre : afficher « 0,72 » donnerait à un chiffre arbitraire l'autorité d'une
mesure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from jarvis.domain.presentation_policy import (
    PresentationOutputPolicy,
    PresentationSituation,
    policy_for,
)
from jarvis.domain.presentation_working_set import (
    MAX_ATTENTION_REASON_CHARS,
    MAX_PROVENANCE_SOURCES,
    MAX_REFERENCE_CHARS,
    MAX_SOURCE_TITLE_CHARS,
    AttentionCategory,
    AttentionItem,
    AttentionSeverity,
    ClaimStatus,
    PresentationWorkingSetError,
    bounded_text,
    check_confidence,
    presentation_id,
    safe_reference_text,
)

#: Le préfixe de trace de cette voie. `background_events.py` l'importe plutôt
#: que de le recopier : deux littéraux qui doivent s'accorder sont deux
#: littéraux qui finissent par diverger.
ATTENTION_KIND = "presentation.attention"

#: La seule nature d'événement que le registre d'arrière-plan doit classer.
ATTENTION_RAISED_KIND = f"{ATTENTION_KIND}.raised"

#: Le libellé affiché, écrit **ici** et non par l'exécutant : c'est une phrase
#: fixe, donc elle ne peut transporter aucune parole. La surface l'affiche tel
#: quel ; le détail vient des références.
ATTENTION_HEADLINES: dict[AttentionCategory, str] = {
    AttentionCategory.CONTRADICTION: "Une affirmation est contredite par une source vérifiée",
    AttentionCategory.MISMATCH: "Un écart a été relevé entre une affirmation et une source",
    AttentionCategory.MISSING_SOURCE: "Une affirmation reste sans source",
    AttentionCategory.STALE_RESOURCE: "Une ressource préparée n'est plus à jour",
}

#: Verdicts qui peuvent devenir une alerte, et la catégorie de chacun. Table
#: **close**, et c'est là qu'est tenue « un échec de recherche n'est pas une
#: contradiction » : `UNCERTAIN` et `SUPPORTED` n'y sont pas, `ASSERTED` non
#: plus. En V1 l'image de la table est le seul `CONTRADICTION` — `MISMATCH`
#: reste déclaré par la Slice 04 mais **inatteignable depuis cette porte**,
#: faute d'un verdict qui le désigne, et le dire vaut mieux que de le laisser
#: croire joignable.
ALERTING_VERDICTS: dict[ClaimStatus, AttentionCategory] = {
    ClaimStatus.CONTRADICTED: AttentionCategory.CONTRADICTION,
}

#: Sous ce seuil, rien n'est signalé. Un seuil de prudence, pas une mesure :
#: voir l'en-tête du module et `docs/presentation-ambient-lane.md` §11.
MIN_ATTENTION_CONFIDENCE = 0.6

#: Au-dessus, la gravité monte d'un cran. Même avertissement.
HIGH_CONFIDENCE = 0.8

#: Pièces retenues par événement. Même borne que `MAX_PROVENANCE_SOURCES` : un
#: avertissement discret cite ses sources, il ne rend pas un dossier.
MAX_ATTENTION_EVIDENCE = MAX_PROVENANCE_SOURCES

#: Ressources préparées citées par un événement. L'architecture les demande ;
#: la borne les empêche de devenir une liste.
MAX_ATTENTION_RESOURCE_REFS = MAX_PROVENANCE_SOURCES

#: Bandes de confiance. Des mots, jamais un nombre — voir l'en-tête.
BAND_HIGH = "high"
BAND_MODERATE = "moderate"


class AttentionRefusal(StrEnum):
    """Pourquoi aucune attention n'a été levée. Un code stable par raison.

    Aucune n'est regroupée sous un cas par défaut : la Slice 06 a payé le prix
    d'une disposition rangée dans un fourre-tout, et un refus qu'on ne sait pas
    nommer est un refus qu'on ne sait pas compter.
    """

    #: L'entrée n'est pas un `FactCheckAssessment`.
    INVALID = "attention_assessment_invalid"
    #: Le jeton du travail ne porte pas la capacité de vérification.
    CAPABILITY_MISSING = "attention_capability_missing"
    #: La recherche n'a pas abouti. **Jamais** une contradiction.
    SEARCH_FAILED = "attention_search_failed"
    #: Verdict hors de `ALERTING_VERDICTS` — y compris `UNCERTAIN`.
    NOT_ALERTING = "attention_not_alerting"
    #: Aucune pièce, ou une pièce sans locator.
    NO_EVIDENCE = "attention_no_evidence"
    #: L'affirmation visée n'est pas dans l'ensemble de travail.
    CLAIM_UNKNOWN = "attention_claim_unknown"
    #: Aucune pièce ne désigne une source connue de l'ensemble de travail.
    PROVENANCE_UNKNOWN = "attention_provenance_unknown"
    #: Confiance sous le seuil de prudence.
    LOW_CONFIDENCE = "attention_low_confidence"
    #: L'événement n'a pas pu être construit (identifiant illégal, etc.).
    NOT_CONSTRUCTIBLE = "attention_not_constructible"


def _check_alerting_table() -> None:
    """« Une recherche ratée ne devient jamais une alerte » est une donnée.

    Vérifié à l'import, comme `_check_capability_table` de la Slice 08 — et
    avec la correction que cette Slice-là a dû faire ensuite : une garde qui
    tourne à chaque import sans jamais rencontrer l'état qu'elle interdit ne
    garde rien. Celle-ci rencontre son état interdit à chaque appel, puisqu'elle
    énumère les verdicts que la table **ne doit pas** contenir plutôt que ceux
    qu'elle contient.
    """

    forbidden = (ClaimStatus.UNCERTAIN, ClaimStatus.SUPPORTED, ClaimStatus.ASSERTED)
    for verdict in forbidden:
        if verdict in ALERTING_VERDICTS:
            raise PresentationWorkingSetError(
                "attention_table_invalid",
                f"{verdict.value} must never raise an attention event",
            )
    for verdict, category in ALERTING_VERDICTS.items():
        if not isinstance(verdict, ClaimStatus) or not isinstance(category, AttentionCategory):
            raise PresentationWorkingSetError(
                "attention_table_invalid", "the alerting table is not typed"
            )
        if category not in ATTENTION_HEADLINES:
            raise PresentationWorkingSetError(
                "attention_table_invalid", f"{category.value} has no headline"
            )


_check_alerting_table()


def attention_output_policy() -> PresentationOutputPolicy:
    """La ligne de politique que D11 gouverne. Lue, jamais recopiée.

    C'est ici que « rien ne parle spontanément » est *constaté* plutôt que
    répété : la ligne vient de la Slice 07, et ce module n'en garde aucune
    copie locale qui pourrait dériver d'elle.
    """

    return policy_for(PresentationSituation.FACT_CHECK_ATTENTION)


def severity_for(confidence: float) -> AttentionSeverity:
    """La gravité, calculée depuis la confiance. Jamais choisie par l'exécutant.

    Deux crans seulement au-dessus du seuil : `INFO` n'est pas joignable depuis
    cette porte, puisqu'une contradiction assez sûre pour être signalée n'est
    pas une information neutre. Le troisième cran reste déclaré par la Slice 04
    pour les producteurs qui viendront.
    """

    return AttentionSeverity.WARNING if confidence >= HIGH_CONFIDENCE else AttentionSeverity.NOTICE


def confidence_band(confidence: float) -> str:
    """Une bande, pas un nombre. Les confiances ne sont pas étalonnées."""

    return BAND_HIGH if confidence >= HIGH_CONFIDENCE else BAND_MODERATE


@dataclass(frozen=True, slots=True)
class AttentionEvidence:
    """Une pièce à conviction : une **référence**, jamais une charge utile.

    `source_id` désigne une `PresentationSource` de l'ensemble de travail —
    c'est par là que la provenance est vérifiable plutôt que déclarée.
    `locator` et `title` passent par `safe_reference_text`, la règle que la
    Slice 04 réserve aux locators et aux titres : c'est ce qui autorise ces
    deux champs-là, et eux seuls, à descendre dans la trace.
    """

    source_id: str
    locator: str
    title: str = ""
    #: La ressource préparée qui la porte, quand la Slice 08 en a rangé une.
    resource_id: str | None = None

    def __post_init__(self) -> None:
        presentation_id("source_id", self.source_id)
        safe_reference_text("evidence locator", self.locator, MAX_REFERENCE_CHARS, locator=True)
        safe_reference_text("evidence title", self.title, MAX_SOURCE_TITLE_CHARS, required=False)
        presentation_id("resource_id", self.resource_id, required=False)

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "locator": self.locator,
            "title": self.title,
            "resource_id": self.resource_id,
        }


@dataclass(frozen=True, slots=True)
class FactCheckAssessment:
    """Ce qu'un exécutant de vérification rend. Un verdict, des pièces, rien de plus.

    Il ne nomme ni la catégorie, ni la gravité, ni l'identifiant de
    l'événement : tout cela est calculé. Il ne peut pas non plus se déclarer
    autorisé — `authorizes_actions` est un `ClassVar`.

    `searched` est le champ que la contrainte « un échec de recherche n'est pas
    une contradiction » rend nécessaire : sans lui, une recherche qui n'a rien
    trouvé et une recherche qui n'a pas eu lieu rendent le même verdict.

    Rien ici ne lève sur un `searched=False` contradictoire : cette valeur
    arrive d'un exécutant, donc d'une entrée non fiable, et la Slice 04 a
    montré qu'un refus **compté** vaut mieux qu'une exception rattrapée puis
    perdue. `decide_attention` le refuse et le nomme.
    """

    claim_id: str
    verdict: ClaimStatus
    confidence: float
    evidence: tuple[AttentionEvidence, ...] = ()
    topic_id: str | None = None
    #: Ressources préparées à ouvrir depuis l'avertissement.
    resource_ids: tuple[str, ...] = ()
    #: Parole reformulée, pour le tour adressé de la Slice 10. Jamais journalisée.
    reason: str = ""
    #: La recherche a-t-elle abouti ? `False` = échec ou absence de source.
    searched: bool = True

    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        presentation_id("claim_id", self.claim_id)
        if not isinstance(self.verdict, ClaimStatus):
            raise TypeError("verdict must be a ClaimStatus")
        check_confidence("confidence", self.confidence)
        if not isinstance(self.searched, bool):
            raise TypeError("searched must be a bool")
        if not isinstance(self.evidence, tuple) or len(self.evidence) > MAX_ATTENTION_EVIDENCE:
            raise ValueError(f"evidence must be a tuple of at most {MAX_ATTENTION_EVIDENCE} pieces")
        for piece in self.evidence:
            if not isinstance(piece, AttentionEvidence):
                raise TypeError("evidence must hold AttentionEvidence")
        presentation_id("topic_id", self.topic_id, required=False)
        _ids("resource_ids", self.resource_ids, MAX_ATTENTION_RESOURCE_REFS)
        bounded_text("attention reason", self.reason, MAX_ATTENTION_REASON_CHARS, required=False)

    @property
    def source_ids(self) -> tuple[str, ...]:
        """Les sources citées, dans l'ordre des pièces, sans doublon."""

        seen: list[str] = []
        for piece in self.evidence:
            if piece.source_id not in seen:
                seen.append(piece.source_id)
        return tuple(seen)


@dataclass(frozen=True, slots=True)
class PresentationAttention:
    """L'événement typé de `docs/02-architecture.md`. Il signale ; il ne parle pas.

    Il ne se construit pas à la main dans le code de production :
    `decide_attention` est la seule porte, et c'est elle qui calcule la
    catégorie, la gravité et l'identifiant. Le constructeur reste ouvert pour
    les tests, avec les mêmes contrôles.
    """

    attention_id: str
    category: AttentionCategory
    severity: AttentionSeverity
    confidence: float
    raised_at: datetime
    claim_id: str
    topic_id: str | None = None
    evidence: tuple[AttentionEvidence, ...] = ()
    resource_ids: tuple[str, ...] = ()
    #: Parole reformulée. Rangée dans l'ensemble de travail, jamais journalisée.
    reason: str = ""

    #: Comme `SpeculativeGrant` et `PresentationContextSnapshot` : des
    #: `ClassVar`, donc `dataclasses.replace` ne peut pas les retourner.
    authorizes_actions: ClassVar[bool] = False
    #: D11, écrite dans le type lui-même. La preuve vivante est
    #: `attention_output_policy()`, qui lit la matrice de la Slice 07.
    requests_speech: ClassVar[bool] = False

    def __post_init__(self) -> None:
        # **Les pièces d'abord.** `to_item()` lit `source_ids`, qui parcourt les
        # pièces : une pièce mal typée y levait une `AttributeError` nue, donc un
        # refus non typé — et `decide_attention`, qui ne rattrape que les refus
        # typés, aurait laissé cette levée traverser sa promesse de ne jamais
        # lever. Trouvé en fermant le survivant de la mutation M14 : le défaut
        # était hors d'atteinte de la porte, mais pas d'un appelant direct.
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ValueError("an attention event carries at least one piece of evidence")
        if len(self.evidence) > MAX_ATTENTION_EVIDENCE:
            raise ValueError(f"at most {MAX_ATTENTION_EVIDENCE} pieces of evidence")
        for piece in self.evidence:
            if not isinstance(piece, AttentionEvidence):
                raise TypeError("evidence must hold AttentionEvidence")
        _ids("resource_ids", self.resource_ids, MAX_ATTENTION_RESOURCE_REFS)
        # `AttentionItem` porte tous les autres contrôles ; le construire est
        # donc la validation, et non une seconde liste de règles qui pourrait
        # dériver de la première.
        self.to_item()

    @property
    def source_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for piece in self.evidence:
            if piece.source_id not in seen:
                seen.append(piece.source_id)
        return tuple(seen)

    @property
    def headline(self) -> str:
        """La phrase fixe de la catégorie. Aucune parole de la salle dedans."""

        return ATTENTION_HEADLINES[self.category]

    @property
    def band(self) -> str:
        return confidence_band(self.confidence)

    def to_item(self) -> AttentionItem:
        """L'enregistrement de la Slice 04, celui que le magasin range.

        C'est lui qui porte `reason` et qui donne `dedup_key` — la coalescence
        `(catégorie, affirmation, sujet)` du magasin est donc la même identité
        que celle de l'événement, et une contradiction signalée deux fois reste
        un seul point d'attention, donc un seul son (D11).
        """

        return AttentionItem(
            attention_id=self.attention_id,
            category=self.category,
            severity=self.severity,
            confidence=self.confidence,
            raised_at=self.raised_at,
            reason=self.reason,
            claim_id=self.claim_id,
            topic_id=self.topic_id,
            source_ids=self.source_ids,
        )

    @property
    def dedup_key(self) -> tuple:
        return self.to_item().dedup_key

    def to_trace_payload(self) -> dict[str, Any]:
        """Ce qui descend dans `trace.jsonl`, donc dans un fichier durable.

        **`reason` n'y est pas, et c'est la seule chose importante de cette
        méthode.** Tout ce qui reste est un identifiant, un nombre, un code, ou
        une référence validée par `safe_reference_text`. La bande est donnée
        plutôt que la confiance brute parce que c'est elle que la surface a le
        droit de montrer ; la confiance brute reste là pour le diagnostic.
        """

        return {
            "attention_id": self.attention_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "confidence": round(float(self.confidence), 3),
            "band": self.band,
            "claim_id": self.claim_id,
            "topic_id": self.topic_id,
            "source_count": len(self.source_ids),
            "evidence": [piece.to_payload() for piece in self.evidence],
            "resource_ids": list(self.resource_ids),
        }


@dataclass(frozen=True, slots=True)
class AttentionDecision:
    """Levée, ou refusée et nommée. Jamais une exception qui se perd.

    `raised` et `refusal` sont exclusifs, et `__post_init__` le tient : une
    décision qui porterait les deux, ou aucun des deux, serait exactement
    l'ambiguïté que ce type existe pour supprimer.
    """

    raised: PresentationAttention | None = None
    refusal: AttentionRefusal | None = None
    #: Ce que l'exécutant avait demandé, pour le compte et le journal.
    verdict: ClaimStatus | None = None

    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if (self.raised is None) == (self.refusal is None):
            raise ValueError("a decision is either raised or refused, never both nor neither")
        if self.raised is not None and not isinstance(self.raised, PresentationAttention):
            raise TypeError("raised must be a PresentationAttention")
        if self.refusal is not None and not isinstance(self.refusal, AttentionRefusal):
            raise TypeError("refusal must be an AttentionRefusal")

    @property
    def alerted(self) -> bool:
        return self.raised is not None

    @property
    def code(self) -> str:
        """Le code stable de la décision, levée comme refusée."""

        if self.refusal is not None:
            return self.refusal.value
        return "attention_raised"


def decide_attention(
    assessment: object,
    *,
    attention_id: str,
    raised_at: datetime,
    known_claim_ids: frozenset[str] | set[str] | tuple[str, ...],
    known_source_ids: frozenset[str] | set[str] | tuple[str, ...],
    may_verify: bool,
) -> AttentionDecision:
    """La porte. Pure, sans horloge implicite, et elle ne lève jamais.

    L'ordre des contrôles n'est pas décoratif : la capacité d'abord (une voie
    qui n'avait pas le droit de vérifier n'a pas le droit d'alerter, quelle que
    soit la qualité de ce qu'elle rend), puis l'échec de recherche, puis le
    verdict, puis les pièces, puis la provenance, puis la confiance. Le
    diagnostic rendu est donc toujours la **première** raison, celle qui est
    utile.

    `known_claim_ids` et `known_source_ids` viennent de l'instantané de la
    Slice 04 : c'est ce qui rend la provenance vérifiée plutôt que déclarée.
    Un exécutant qui invente une source ne passe pas.
    """

    if not isinstance(assessment, FactCheckAssessment):
        return AttentionDecision(refusal=AttentionRefusal.INVALID)
    verdict = assessment.verdict
    if not may_verify:
        return AttentionDecision(refusal=AttentionRefusal.CAPABILITY_MISSING, verdict=verdict)
    if not assessment.searched:
        # La contrainte la plus explicite de la Slice, et le cas hostile :
        # un exécutant qui rend `CONTRADICTED` sur une recherche ratée est
        # refusé **ici**, avant que le verdict ne soit seulement regardé.
        return AttentionDecision(refusal=AttentionRefusal.SEARCH_FAILED, verdict=verdict)
    category = ALERTING_VERDICTS.get(verdict)
    if category is None:
        return AttentionDecision(refusal=AttentionRefusal.NOT_ALERTING, verdict=verdict)
    if not assessment.evidence or any(not piece.locator for piece in assessment.evidence):
        return AttentionDecision(refusal=AttentionRefusal.NO_EVIDENCE, verdict=verdict)
    if assessment.claim_id not in set(known_claim_ids):
        return AttentionDecision(refusal=AttentionRefusal.CLAIM_UNKNOWN, verdict=verdict)
    known = set(known_source_ids)
    if not any(piece.source_id in known for piece in assessment.evidence):
        return AttentionDecision(refusal=AttentionRefusal.PROVENANCE_UNKNOWN, verdict=verdict)
    if float(assessment.confidence) < MIN_ATTENTION_CONFIDENCE:
        return AttentionDecision(refusal=AttentionRefusal.LOW_CONFIDENCE, verdict=verdict)
    try:
        raised = PresentationAttention(
            attention_id=attention_id,
            category=category,
            severity=severity_for(float(assessment.confidence)),
            confidence=float(assessment.confidence),
            raised_at=raised_at,
            claim_id=assessment.claim_id,
            topic_id=assessment.topic_id,
            evidence=assessment.evidence,
            resource_ids=assessment.resource_ids,
            reason=assessment.reason,
        )
    except (PresentationWorkingSetError, TypeError, ValueError):
        # Un identifiant d'événement illégal ou une horloge naïve : le refus se
        # compte, il ne remonte pas. Le texte de l'exception n'est pas repris —
        # il pourrait contenir la valeur refusée, donc de la parole.
        return AttentionDecision(refusal=AttentionRefusal.NOT_CONSTRUCTIBLE, verdict=verdict)
    return AttentionDecision(raised=raised, verdict=verdict)


def _ids(name: str, values: object, limit: int) -> None:
    if not isinstance(values, tuple) or len(values) > limit:
        raise ValueError(f"{name} must be a tuple of at most {limit} identifiers")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not repeat an identifier")
    for item in values:
        presentation_id(f"{name} entry", item)


__all__ = [
    "ATTENTION_KIND",
    "ATTENTION_RAISED_KIND",
    "ATTENTION_HEADLINES",
    "ALERTING_VERDICTS",
    "MIN_ATTENTION_CONFIDENCE",
    "HIGH_CONFIDENCE",
    "MAX_ATTENTION_EVIDENCE",
    "MAX_ATTENTION_RESOURCE_REFS",
    "BAND_HIGH",
    "BAND_MODERATE",
    "AttentionRefusal",
    "AttentionEvidence",
    "FactCheckAssessment",
    "PresentationAttention",
    "AttentionDecision",
    "attention_output_policy",
    "confidence_band",
    "decide_attention",
    "severity_for",
]
