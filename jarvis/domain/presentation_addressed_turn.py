"""Le tour adressé prioritaire : ce qu'il résout, contre quoi, et dans quel ordre.

Handoff `jarvis-presentation-interaction-mode`, Slice 10. Module **pur** : aucune
E/S, aucune importation de `jarvis.core` ni de `jarvis.runtime`, aucune horloge
murale. Il ne décide ni de la parole (la matrice de la Slice 01 le fait déjà,
lue par la Slice 07) ni de la priorité d'exécution (la Slice 08 la tient) : il
dit **à quoi « ça » se rapporte** et **quelle ressource préparée peut répondre
sans mentir**.

La précédence de contexte, et pourquoi elle ne peut pas s'inverser
------------------------------------------------------------------

Décision D06 : le tour explicite reçoit l'ensemble de travail enrichi **et** le
fil de parole récent. Les deux ne sont pas à égalité. Le fil dit ce qui vient
d'être dit ; l'ensemble de travail dit ce que l'analyse a fini de comprendre, et
elle peut avoir trente secondes de retard. Un déictique résolu contre l'ensemble
de travail désignerait donc ce dont on parlait *avant*.

La règle est donc :

1. **le référent est toujours l'énonciation la plus récente du fil.** L'ensemble
   de travail ne fait jamais autorité sur « ce qui vient d'être dit » ;
2. une ressource préparée ne peut répondre à un déictique que si elle est
   **ancrée au référent** : sa provenance cite la même énonciation, ou son sujet
   fait partie des *sujets du référent* (`referent_topic_ids`) — et non « d'un
   sujet encore vivant », qui montrait l'écran du sujet précédent ;
3. tout le reste est **périmé** : préparé à partir d'une parole plus ancienne que
   ce que l'utilisateur vient de désigner. On rafraîchit, on ne montre pas.

Les deux moitiés se comparent sur une seule échelle, le rang d'énonciation, et
ce rang est **attribué par le magasin**. Une version précédente de cet en-tête en
concluait que la précédence tenait par une **dépendance de données** : c'était
faux, et c'est la correction la plus importante de cette Slice. La formule venait
de la Slice 06, où elle est juste — là-bas l'enfilement *a besoin* d'un rang que
seul le magasin peut avoir attribué — et elle avait été généralisée en propriété
du **magasin**, que le magasin ne tenait pas : `apply()` recopiait
`provenance.sequence` sans contrôle, donc un enregistrement citant le rang 54
contre un fil s'arrêtant à 4 éteignait la garde du point 3 pour de bon.

C'est une propriété du magasin **maintenant** : `apply()` borne la fraîcheur
qu'un enregistrement peut réclamer à `assigned_sequence`, le plus haut rang que
le magasin ait attribué dans cette séance, et le dit quand il rabote. Et
`cited_rank` referme la même porte du côté lecture, pour qu'aucun résolveur
n'ait à faire confiance au champ.

C'est la forme exécutable de « un cache périmé ne doit jamais l'emporter sur une
parole plus fraîche ».

Le déictique
------------

Lexical, français, petit, et ses limites sont écrites §
`DEICTIC_MARKERS`. Même parti pris que le classement de la Slice 07 : les
résidus penchent du côté sûr. Ici le côté sûr est **l'inverse** de celui de la
parole — un déictique manqué fait traiter le tour comme une demande nommée, que
le cerveau résoudra avec tout le contexte projeté ; un déictique inventé ferait
au pire poser une question de clarification. Aucun des deux ne montre un mauvais
écran, qui est le seul défaut que ce module existe pour empêcher.

Ce que ce module ne fait pas
----------------------------

Il ne rapproche pas une **demande nommée** (« montre-moi le bilan Q3 ») d'une
ressource préparée. Le faire ici demanderait un second classement lexical, plus
faible que celui du cerveau. `ResourceVerdict.NOT_REQUESTED` le dit plutôt que
de le laisser deviner.

L'échappatoire, elle, devait être vraie : « le cerveau reçoit de toute façon la
projection ». Elle ne l'était pas — la projection ne portait **aucune** ressource
préparée, donc une demande nommée ne réutilisait rien *et* le cerveau ignorait
que le matériel existait. `AddressedTurnContext.resources` les lui nomme
maintenant, bornées et sans charge utile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from jarvis.domain.explicit_address import ExplicitAddressTrigger
from jarvis.domain.output_disposition import OutputDisposition
from jarvis.domain.presentation_policy import PresentationSituation, policy_for
from jarvis.domain.presentation_working_set import (
    MAX_TAIL_ENTRY_CHARS,
    PreparedResource,
    PresentationContextSnapshot,
    ResourceKind,
    ResourceTemperature,
    compact_chars,
)
from jarvis.domain.reflex_policy import normalized_tokens

#: Durée pendant laquelle un déclencheur continue d'adresser la parole qui le
#: suit. Au-delà, la phrase entendue n'est plus « le tour » : elle appartient à
#: la salle, et la traiter comme adressée donnerait à une conversation ordinaire
#: l'autorité d'agir, ce que D03 interdit. Douze secondes : le temps de dire une
#: commande, plus la latence de transcription d'un segment.
MAX_ADDRESSED_WINDOW_S = 12.0

#: Écart maximal admis entre l'horloge du service et l'estampille du
#: déclencheur. Au-delà, ce ne sont pas deux lectures de la même horloge : c'est
#: une erreur de câblage, et la latence qu'on en tirerait serait un nombre
#: plausible et faux.
#:
#: La valeur est celle de la fenêtre, et ce n'est pas un hasard : un déclencheur
#: plus vieux que sa propre fenêtre ne peut plus adresser la phrase en cours, il
#: n'existe donc aucun cas où continuer aide. Sans ce plafond, une horloge en
#: avance de cinq minutes refusait **tous** les tours en
#: `addressed_window_expired` — la fonctionnalité morte sous un code qui accuse
#: l'utilisateur d'avoir parlé trop tard.
MAX_TRIGGER_CLOCK_SKEW_S = MAX_ADDRESSED_WINDOW_S

#: Marge **avant** le déclencheur pendant laquelle une parole déjà commencée
#: reste celle du tour. C'est le pendant logique du pré-roll PCM de la Slice 05
#: (`CommandPreRoll`) : le détecteur de mot d'éveil ne se déclenche jamais sur la
#: première syllabe.
DEFAULT_PREROLL_S = 1.5

#: Énonciations du fil projetées dans le contexte du tour. Le fil en retient
#: seize ; huit suffisent à résoudre un déictique et laissent de la place au
#: reste sous le budget.
MAX_ADDRESSED_TAIL_ENTRIES = 8
MAX_ADDRESSED_TOPICS = 6
MAX_ADDRESSED_CLAIMS = 6
MAX_ADDRESSED_ENTITIES = 8
MAX_ADDRESSED_SOURCES = 4
MAX_ADDRESSED_QUESTIONS = 4
MAX_ADDRESSED_ATTENTION = 3
#: Ressources préparées nommées au cerveau. Le magasin en retient seize ; six
#: suffisent à ce qu'une demande nommée trouve la sienne sans que la projection
#: devienne un catalogue.
MAX_ADDRESSED_RESOURCES = 6

#: Budget de **prompt** de cette projection, en forme JSON compacte. C'est la
#: borne que `docs/presentation-working-set.md` annonçait comme appartenant à la
#: Slice 10, à côté de `MAX_BRAIN_WORK_CONTEXT_CHARS` pour le travail — et non le
#: plafond dur `MAX_WORKING_SET_CHARS` (120 000), qui prouve seulement que le
#: magasin est fini. Même valeur que le contexte de travail : c'est le même
#: budget d'attention d'un même tour.
MAX_ADDRESSED_CONTEXT_CHARS = 6_000

#: Jetons déictiques purs. Volontairement **sans** `ce` / `cet` / `cette` / `la`
#: (accentué ou non) : ce sont des déterminants ou des articles, et « montre-moi
#: la courbe » nomme son objet. Sans accents, parce que `normalized_tokens`
#: décompose (« ça » → `ca`, « là » → `la`) — ce qui est précisément pourquoi
#: `la` ne peut pas entrer ici.
DEICTIC_MARKERS: frozenset[str] = frozenset(
    {"ca", "cela", "ceci", "celui", "celle", "ceux", "celles"}
)

#: Tournures déictiques de plusieurs mots, cherchées dans la phrase normalisée.
#: Elles portent l'ambiguïté que les jetons isolés ne portent pas : « le
#: dernier » seul est un adjectif, « le dernier » suivi de rien désigne.
DEICTIC_PHRASES: tuple[str, ...] = (
    "ce dernier", "cette derniere", "ces derniers", "ces dernieres",
    "le dernier", "la derniere", "les derniers", "les dernieres",
    "ce dont on parle", "ce dont je parle", "de quoi on parle",
    "ce que je viens de dire", "ce qu on vient de dire", "ce qu il vient de dire",
    "ce truc", "ce machin", "ce point",
)

#: Bornes de lecture du texte adressé. Même valeur que le classement de la
#: Slice 07 : deux bornes différentes sur le même texte donneraient deux
#: lectures du même tour.
MAX_ADDRESSED_TEXT_CHARS = 4096


class PresentationAddressedTurnError(ValueError):
    """Refus typé, code stable et anglais, message pour un humain francophone."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ContextOrigin(StrEnum):
    """D'où vient le référent d'un déictique.

    `TAIL` : de la parole récente, non enrichie — le cas que D06 protège.
    `WORKING_SET` : l'enrichissement a rattrapé cette énonciation, donc le même
    référent est aussi connu de l'ensemble de travail, avec ses sujets et ses
    faits.

    **Ne décide rien, et c'est écrit ici pour qu'on ne le croie pas.** Le
    référent est le même dans les deux cas ; la garde de fraîcheur, elle, relit
    le prédicat directement (`observed_sequence >= referent.sequence`) au lieu
    de lire cette valeur, parce qu'une garde qui dépend d'un champ de trace finit
    par dépendre de qui le remplit. C'est donc de la **télémétrie**, plus un
    indice rendu au modèle : « je n'ai que la phrase » et « j'ai aussi ce que
    l'analyse en a tiré » ne s'utilisent pas pareil quand on répond.
    """

    TAIL = "tail"
    WORKING_SET = "working_set"


class ResourceVerdict(StrEnum):
    """Ce qu'on peut faire d'une ressource préparée pour ce tour-ci."""

    #: Ancrée au référent, vivante : on la montre, sans rien re-préparer.
    REUSABLE = "reusable"
    #: Préparée à partir d'une parole plus ancienne que ce qui vient d'être
    #: désigné, ou l'enrichissement n'a pas encore atteint le référent.
    STALE = "stale"
    #: Deux candidates également ancrées : on demande laquelle plutôt que d'en
    #: choisir une au hasard.
    AMBIGUOUS = "ambiguous"
    #: Rien de préparé qui puisse répondre.
    ABSENT = "absent"
    #: Le tour ne désigne rien : il nomme son objet, ou ce n'est pas une
    #: commande visuelle. Ce module ne rapproche pas une demande nommée.
    NOT_REQUESTED = "not_requested"


class AddressedTurnAction(StrEnum):
    """Ce que le tour va faire. Une seule valeur, décidée une fois."""

    #: Montrer ce qui était déjà préparé.
    SHOW_PREPARED = "show_prepared"
    #: Re-préparer, parce que ce qu'on a est périmé ou absent (P1, pas P0).
    REFRESH = "refresh"
    #: Demander laquelle. Audible : `QUESTION` est une nature de sûreté de la
    #: ligne `VISUAL_COMMAND` depuis la Slice 07.
    CLARIFY = "clarify"
    #: Rien à résoudre ici : le cerveau reçoit la projection et répond.
    ASK_BRAIN = "ask_brain"


@dataclass(frozen=True, slots=True)
class AddressedWindow:
    """La fenêtre pendant laquelle la parole appartient au déclencheur.

    Elle s'ouvre **avant** le déclencheur (pré-roll) et se ferme après lui. Les
    deux bornes sont sur l'horloge monotone du déclencheur, jamais sur une
    horloge murale : c'est la même raison qu'à la Slice 05 — une correction NTP
    ferait reculer le temps et une fenêtre pourrait se fermer avant de s'ouvrir.
    """

    trigger: ExplicitAddressTrigger
    preroll_s: float = DEFAULT_PREROLL_S
    max_wait_s: float = MAX_ADDRESSED_WINDOW_S

    #: Une fenêtre dit *quand* écouter, jamais *quoi faire*.
    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, ExplicitAddressTrigger):
            raise PresentationAddressedTurnError(
                "addressed_window_trigger_invalid",
                "Une fenêtre adressée se construit sur un ExplicitAddressTrigger.",
            )
        for name in ("preroll_s", "max_wait_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise PresentationAddressedTurnError(
                    "addressed_window_bound_invalid",
                    f"La borne {name} doit être un nombre positif ou nul.",
                )
        if self.max_wait_s <= 0:
            raise PresentationAddressedTurnError(
                "addressed_window_bound_invalid",
                "Une fenêtre qui se ferme à l'instant où elle s'ouvre n'adresse rien.",
            )

    @property
    def opens_at_s(self) -> float:
        """Jamais négatif : `time.monotonic()` est positif sur les plateformes visées."""

        return max(0.0, self.trigger.monotonic_s - float(self.preroll_s))

    @property
    def closes_at_s(self) -> float:
        return self.trigger.monotonic_s + float(self.max_wait_s)

    def covers(self, monotonic_s: float) -> bool:
        """La parole datée de `monotonic_s` appartient-elle à ce déclencheur ?"""

        if isinstance(monotonic_s, bool) or not isinstance(monotonic_s, (int, float)):
            return False
        return self.opens_at_s <= float(monotonic_s) <= self.closes_at_s

    def expired(self, now: float) -> bool:
        """La fenêtre est-elle passée ? Une fenêtre passée n'adresse plus rien."""

        if isinstance(now, bool) or not isinstance(now, (int, float)):
            return True
        return float(now) > self.closes_at_s

    def to_trace_payload(self) -> dict[str, Any]:
        """Journalisable : des nombres et une source. Jamais de parole, jamais de PCM."""

        return {
            "source": self.trigger.source.value,
            "label": self.trigger.label,
            "trigger_sequence": self.trigger.sequence,
            "trigger_monotonic_s": round(self.trigger.monotonic_s, 6),
            "opens_at_s": round(self.opens_at_s, 6),
            "closes_at_s": round(self.closes_at_s, 6),
        }


@dataclass(frozen=True, slots=True)
class ResolvedReferent:
    """Ce que « ça » désigne, et ce qu'on sait de sa fraîcheur.

    `sequence` est le rang attribué par le magasin — la seule échelle sur
    laquelle le fil et l'ensemble de travail se comparent.
    """

    utterance_id: str
    sequence: int
    spoken_at: datetime
    origin: ContextOrigin
    enrichment_lag_entries: int
    enrichment_lag_s: float

    def to_trace_payload(self) -> dict[str, Any]:
        return {
            "utterance_id": self.utterance_id,
            "sequence": self.sequence,
            "origin": self.origin.value,
            "enrichment_lag_entries": self.enrichment_lag_entries,
            "enrichment_lag_s": round(self.enrichment_lag_s, 3),
        }


@dataclass(frozen=True, slots=True)
class ResourceResolution:
    """Ce qu'une ressource préparée peut faire pour ce tour, et pourquoi."""

    verdict: ResourceVerdict
    #: Identifiant retenu. Non vide seulement pour `REUSABLE`.
    resource_id: str = ""
    #: Nature de la référence retenue ; utile parce qu'un `scene_object` se
    #: révèle et qu'une autre ressource se cite.
    kind: ResourceKind | None = None
    #: Identifiants des candidates restées à égalité. Bornée à deux : dire
    #: « lesquelles » n'exige pas de toutes les nommer.
    tied: tuple[str, ...] = ()
    #: Code stable disant *pourquoi* ce verdict.
    code: str = ""

    def __post_init__(self) -> None:
        if self.verdict is ResourceVerdict.REUSABLE and not self.resource_id:
            raise PresentationAddressedTurnError(
                "addressed_resolution_invalid",
                "Une ressource réutilisable porte forcément son identifiant.",
            )
        if self.verdict is not ResourceVerdict.REUSABLE and self.resource_id:
            raise PresentationAddressedTurnError(
                "addressed_resolution_invalid",
                "Seule une ressource réutilisable nomme un identifiant retenu.",
            )

    def to_trace_payload(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "resource_id": self.resource_id,
            "kind": None if self.kind is None else self.kind.value,
            "tied": list(self.tied),
            "code": self.code,
        }


@dataclass(frozen=True, slots=True)
class AddressedTurnContext:
    """La projection remise au tour adressé. Deux sorties, une seule parlante.

    `to_brain_context()` porte de la **parole** — le fil récent, les libellés,
    les affirmations, et le `reason` d'un point d'attention. C'est voulu : c'est
    tout l'objet de D06, et c'est la seule façon de répondre à « qu'est-ce que tu
    as trouvé ? » (`HV-PRES-ALERT-01`). Elle va au modèle, en mémoire, dans le
    processus.

    `to_trace_payload()` porte des comptes, des identifiants et des codes. Elle
    va au journal.

    Les deux sorties sont nommées différemment **exprès**. La Slice 09 a laissé
    une précondition : `reason` est le seul champ qui puisse transporter de la
    parole de salle, et il traverse déjà `AttentionItem.to_payload()` →
    `PresentationWorkingSet.to_payload()` → `PresentationContextSnapshot
    .to_payload()`. Tant que rien n'appelle ces sérialiseurs, la contrainte tient
    *par absence*. Ce module est celui qui voulait lire `reason` : il le lit
    **sur l'objet, en mémoire**, et n'appelle aucun de ces trois sérialiseurs —
    ni ici ni dans le service. Un test d'AST le prouve en interdisant tout appel
    de `to_payload` dans les deux modules de la Slice, parce qu'aucun test de
    comportement ne sait prouver l'absence d'un appel.

    `authorizes_actions` est figé à faux : une projection de contexte est du
    contexte, jamais un ordre (D03), comme l'instantané dont elle sort.
    """

    session_id: str
    revision: int
    situation: PresentationSituation
    evidence: str
    disposition: OutputDisposition
    deictic: str
    referent: ResolvedReferent | None
    resource: ResourceResolution
    tail: tuple[tuple[str, int, str], ...] = ()
    #: Ressources préparées encore vivantes : identifiant, nature, titre, sujet,
    #: température. Des **références**, jamais une charge utile — c'est déjà la
    #: règle de la Slice 04 et elle ne change pas ici.
    #:
    #: Elles sont projetées parce que sans elles la porte de sortie de ce module
    #: était fausse : une demande **nommée** (« montre-moi le bilan Q3 ») n'est
    #: pas résolue ici, et la raison écrite partout était que « le cerveau reçoit
    #: de toute façon la projection ». Il la recevait sans les ressources, donc
    #: rien ne réutilisait le matériel préparé **et** le cerveau ignorait qu'il
    #: existait. La règle « ce module ne rapproche pas un nom d'une ressource »
    #: tient ; ce qui ne tenait pas, c'était l'échappatoire.
    resources: tuple[tuple[str, str, str, str, str], ...] = ()
    topics: tuple[tuple[str, str], ...] = ()
    claims: tuple[tuple[str, str, str], ...] = ()
    entities: tuple[tuple[str, str], ...] = ()
    sources: tuple[tuple[str, str, str], ...] = ()
    questions: tuple[tuple[str, str], ...] = ()
    attention: tuple[tuple[str, str, str, str], ...] = ()
    #: Sections retirées pour tenir dans le budget, dans l'ordre où elles sont
    #: tombées. Une projection qui se tait sur ce qu'elle a coupé ferait croire
    #: à un ensemble de travail vide.
    clipped: tuple[str, ...] = ()

    authorizes_actions: ClassVar[bool] = False

    @property
    def chars(self) -> int:
        return compact_chars(self.to_brain_context())

    def to_brain_context(self) -> dict[str, Any]:
        """Ce que le cerveau reçoit. **Porte de la parole**, par construction.

        Ordonnée de la plus fraîche à la plus ancienne dans le fil, parce que la
        précédence de ce module doit rester lisible dans ce qu'il rend, et pas
        seulement dans ce qu'il calcule.
        """

        return {
            "session_id": self.session_id,
            "revision": self.revision,
            "situation": self.situation.value,
            "evidence": self.evidence,
            "disposition": self.disposition.value,
            "authorizes_actions": self.authorizes_actions,
            "deictic": self.deictic,
            "referent": None if self.referent is None else {
                "utterance_id": self.referent.utterance_id,
                "sequence": self.referent.sequence,
                "spoken_at": self.referent.spoken_at.isoformat(),
                "origin": self.referent.origin.value,
                "enrichment_lag_entries": self.referent.enrichment_lag_entries,
                "enrichment_lag_s": round(self.referent.enrichment_lag_s, 3),
            },
            "prepared_resource": {
                "verdict": self.resource.verdict.value,
                "resource_id": self.resource.resource_id,
                "kind": None if self.resource.kind is None else self.resource.kind.value,
                "code": self.resource.code,
            },
            "recent_speech": [
                {"utterance_id": item[0], "sequence": item[1], "text": item[2]}
                for item in self.tail
            ],
            "prepared_resources": [
                {"resource_id": item[0], "kind": item[1], "title": item[2],
                 "topic_id": item[3] or None, "temperature": item[4]}
                for item in self.resources
            ],
            "topics": [{"topic_id": item[0], "label": item[1]} for item in self.topics],
            "claims": [
                {"claim_id": item[0], "statement": item[1], "status": item[2]}
                for item in self.claims
            ],
            "entities": [{"entity_id": item[0], "label": item[1]} for item in self.entities],
            "sources": [
                {"source_id": item[0], "title": item[1], "reference": item[2]}
                for item in self.sources
            ],
            "open_questions": [{"question_id": item[0], "text": item[1]} for item in self.questions],
            "attention": [
                {"attention_id": item[0], "category": item[1], "severity": item[2], "reason": item[3]}
                for item in self.attention
            ],
            "clipped": list(self.clipped),
        }

    def to_trace_payload(self) -> dict[str, Any]:
        """Journalisable. Des comptes, des identifiants, des codes. Rien de dit."""

        return {
            "session_id": self.session_id,
            "revision": self.revision,
            "situation": self.situation.value,
            "evidence": self.evidence,
            "disposition": self.disposition.value,
            # Le jeton, pas un booléen. Les deux viennent de lexiques clos
            # (`DEICTIC_MARKERS`, `DEICTIC_PHRASES`), exactement comme
            # `evidence` : un booléen coûtait la seule question qu'on se pose
            # ensuite, « pourquoi ça n'a pas été lu comme un déictique ».
            "deictic": self.deictic,
            "referent": None if self.referent is None else self.referent.to_trace_payload(),
            "resource": self.resource.to_trace_payload(),
            "tail_entries": len(self.tail),
            "resources": len(self.resources),
            "topics": len(self.topics),
            "claims": len(self.claims),
            "entities": len(self.entities),
            "sources": len(self.sources),
            "questions": len(self.questions),
            "attention": len(self.attention),
            "clipped": list(self.clipped),
            "chars": self.chars,
        }


# --------------------------------------------------------------------------
# Lecture du texte adressé
# --------------------------------------------------------------------------


def deictic_marker(text: object) -> str:
    """La marque déictique du tour, ou `""`. Ne lève jamais.

    Ne lève jamais parce que le texte vient d'une transcription temps réel, et
    qu'un tour adressé qu'on n'a pas su lire doit se comporter comme un tour
    ordinaire — jamais comme une panne. C'est la position de la Slice 07 sur son
    propre classement, tenue ici pour la même raison.
    """

    raw = text if isinstance(text, str) else ""
    tokens = normalized_tokens(raw[:MAX_ADDRESSED_TEXT_CHARS])
    phrase = " ".join(tokens)
    for marker in DEICTIC_PHRASES:
        if phrase == marker or f" {marker} " in f" {phrase} ":
            return marker.replace(" ", "_")
    for token in tokens:
        if token in DEICTIC_MARKERS:
            return token
    return ""


# --------------------------------------------------------------------------
# Précédence de contexte
# --------------------------------------------------------------------------


def resolve_referent(snapshot: object) -> ResolvedReferent | None:
    """Ce que désigne un déictique : l'énonciation la plus récente du fil.

    **Toujours le fil, jamais l'ensemble de travail.** L'ensemble de travail ne
    fait pas autorité sur « ce qui vient d'être dit » : il peut être en retard,
    et `enrichment_lag_entries` dit de combien. Ce que l'origine change, c'est
    seulement ce qu'on *sait en plus* du référent : `WORKING_SET` veut dire que
    l'enrichissement a rattrapé cette énonciation-là, donc ses sujets et ses
    faits sont disponibles ; `TAIL` veut dire qu'on n'a que la phrase.

    Rend `None` quand le fil est vide : il n'y a alors rien à désigner, et
    inventer un référent ferait montrer le dernier écran préparé, c'est-à-dire
    exactement l'erreur que D06 existe pour empêcher.
    """

    if not isinstance(snapshot, PresentationContextSnapshot):
        return None
    latest = snapshot.tail.latest
    if latest is None:
        return None
    origin = (
        ContextOrigin.WORKING_SET
        if snapshot.working_set.observed_sequence >= latest.sequence
        else ContextOrigin.TAIL
    )
    return ResolvedReferent(
        utterance_id=latest.utterance_id,
        sequence=latest.sequence,
        spoken_at=latest.spoken_at,
        origin=origin,
        enrichment_lag_entries=snapshot.enrichment_lag_entries,
        enrichment_lag_s=snapshot.enrichment_lag_s,
    )


def cited_rank(record: object, *, ceiling: int) -> int:
    """Le rang qu'un enregistrement cite, **borné par ce que le magasin a rangé**.

    Un enregistrement sans provenance — une source, un point d'attention — n'en
    cite aucun : il vient d'une recherche, pas d'une parole, et rend 0.

    Le plafond est `observed_sequence`, que le magasin borne lui-même au dernier
    rang qu'il a attribué. Le relire ici plutôt que de faire confiance au champ
    ferme la même porte une seconde fois, du côté lecture : un producteur qui
    gonfle un rang ne peut ni faire avancer la fraîcheur de l'ensemble, ni faire
    passer son enregistrement pour plus proche du référent qu'il ne l'est.
    """

    provenance = getattr(record, "provenance", None)
    if provenance is None:
        return 0
    return min(int(provenance.sequence), int(ceiling))


def referent_topic_ids(working_set: object, *, referent: ResolvedReferent) -> frozenset[str]:
    """Les sujets **du référent** : ceux que nomme ce que l'analyse en a tiré.

    C'est la correction d'un défaut central, et il vaut d'être écrit ici. La
    première version retenait *n'importe quel sujet vivant*, ce qui a l'air
    prudent et ne l'est pas :

    ```text
    u-001 « regardons le bilan Q3 »      -> sujet t-bilan, ressource r-bilan préparée
    u-002 « parlons de la trésorerie »   -> sujet t-treso committé
    « montre-moi ça »                    -> r-bilan : l'écran du sujet précédent
    ```

    L'enrichissement est **à jour** dans cette trace — `observed_sequence` vaut
    le rang du référent, le retard est nul — donc aucune garde de fraîcheur ne
    pouvait l'attraper. Et ce n'est pas un cas rare : l'analyse produit un sujet
    pour une énonciation neuve bien avant qu'une *ressource* existe pour elle,
    donc toute commande déictique lancée dans cette fenêtre montrait le sujet
    d'avant. « Montrer le mauvais écran » atteint par la seule direction que les
    gardes ne surveillaient pas.

    La règle est donc **au référent** et non « vivant » : un sujet appartient au
    référent quand un enregistrement qui le nomme cite une énonciation de rang
    au moins égal à celui du référent. Un sujet, une entité, une affirmation ou
    une question suffisent ; une **ressource** ne compte pas — elle se porterait
    caution à elle-même.

    ## Le coût, assumé et épinglé par un test

    `_coalesce` ne réécrit jamais la provenance d'un sujet (règle de la Slice 04,
    et elle est juste : un fait doit continuer de citer l'énonciation qui l'a
    produit). Un sujet **re-mentionné** garde donc le rang de sa première
    mention et ne rejoint pas cet ensemble : « toujours sur le bilan » puis
    « montre-moi ça » **rafraîchit** au lieu de réutiliser, tant que l'analyse
    n'a pas aussi produit une entité, une affirmation ou une question de rang
    frais sur ce sujet — ce qu'elle fait couramment.

    C'est une réutilisation perdue, pas un mauvais écran, et c'est le côté que
    cette Slice choisit partout ailleurs. Faire mieux demanderait à l'ensemble
    de travail de retenir, par sujet, la dernière énonciation qui l'a mentionné :
    un champ qui n'existe pas et qui appartiendrait à la Slice 04.
    """

    ceiling = int(getattr(working_set, "observed_sequence", 0))
    floor = referent.sequence
    named: set[str] = set()
    for item in getattr(working_set, "topics", ()):
        if cited_rank(item, ceiling=ceiling) >= floor:
            named.add(item.topic_id)
    for name in ("entities", "claims", "questions"):
        for item in getattr(working_set, name, ()):
            if item.topic_id is not None and cited_rank(item, ceiling=ceiling) >= floor:
                named.add(item.topic_id)
    return frozenset(named)


def _resource_rank(resource: PreparedResource, *, ceiling: int) -> tuple:
    """Ordre de préférence : la plus fraîchement ancrée, puis la plus chaude.

    **Sans identifiant final**, contrairement aux `sort_key` du magasin. Là-bas
    l'identifiant rend l'éviction déterministe ; ici il rendrait deux candidates
    strictement équivalentes artificiellement départageables, et « montre-moi
    ça » choisirait au hasard alphabétique au lieu de demander laquelle.
    """

    return (
        cited_rank(resource, ceiling=ceiling),
        resource.temperature.rank,
        resource.last_used_at,
    )


def resolve_prepared_resource(
    snapshot: object,
    *,
    referent: ResolvedReferent | None,
    retired_resource_ids: tuple[str, ...] = (),
) -> ResourceResolution:
    """La ressource préparée qui peut répondre au déictique, ou pourquoi aucune.

    L'ordre des refus **est** le contrat, parce que c'est le premier qui est
    journalisé et c'est lui qui explique la séance :

    1. pas de référent — le fil est vide, rien n'a été désigné ;
    2. rien de préparé, une fois les **retraits** et les ressources **froides**
       écartés. Une ressource retirée ne ressuscite pas (le magasin le tient
       déjà côté écriture ; ici c'est le côté lecture), et une ressource
       `discardable` a perdu son sujet ou dort depuis dix minutes ;
    3. l'enrichissement n'a pas atteint le référent : **toutes** les candidates
       sont alors ancrées à une parole plus ancienne que ce qui vient d'être
       désigné. C'est le cœur de D06, et c'est un refus, pas un choix par
       défaut ;
    4. ancrage **au référent** : soit la provenance de la ressource cite
       l'énonciation désignée, soit son sujet fait partie des **sujets du
       référent** — voir `referent_topic_ids`, et le défaut central qu'il
       corrige ;
    5. égalité stricte entre les deux meilleures : on demande laquelle.
    """

    if referent is None:
        return ResourceResolution(ResourceVerdict.ABSENT, code="addressed_no_recent_speech")
    if not isinstance(snapshot, PresentationContextSnapshot):
        return ResourceResolution(ResourceVerdict.ABSENT, code="addressed_snapshot_unreadable")
    retired = frozenset(retired_resource_ids)
    working_set = snapshot.working_set
    candidates = [
        item
        for item in working_set.resources
        if item.resource_id not in retired
        and item.temperature is not ResourceTemperature.DISCARDABLE
    ]
    if not candidates:
        return ResourceResolution(ResourceVerdict.ABSENT, code="addressed_no_live_resource")
    if working_set.observed_sequence < referent.sequence:
        # Le cache ne peut pas répondre à une phrase qu'il n'a pas encore vue.
        # Rafraîchir coûte un tour ; montrer le mauvais écran coûte la confiance.
        return ResourceResolution(
            ResourceVerdict.STALE, code="addressed_enrichment_behind_referent"
        )
    direct = [
        item for item in candidates if item.provenance.utterance_id == referent.utterance_id
    ]
    if direct:
        pool, code = direct, "addressed_resource_anchored_to_referent"
    else:
        topics = referent_topic_ids(working_set, referent=referent)
        pool = [item for item in candidates if item.topic_id in topics]
        code = "addressed_resource_anchored_to_referent_topic"
        if not pool:
            return ResourceResolution(
                ResourceVerdict.STALE, code="addressed_no_resource_for_referent"
            )
    ceiling = working_set.observed_sequence
    ordered = sorted(pool, key=lambda item: _resource_rank(item, ceiling=ceiling), reverse=True)
    best = ordered[0]
    runner_up = (
        _resource_rank(ordered[1], ceiling=ceiling) if len(ordered) > 1 else None
    )
    if runner_up is not None and runner_up == _resource_rank(best, ceiling=ceiling):
        return ResourceResolution(
            ResourceVerdict.AMBIGUOUS,
            tied=tuple(item.resource_id for item in ordered[:2]),
            code="addressed_resource_ambiguous",
        )
    return ResourceResolution(
        ResourceVerdict.REUSABLE,
        resource_id=best.resource_id,
        kind=best.reference.kind,
        code=code,
    )


def decide_action(
    situation: PresentationSituation, resolution: ResourceResolution
) -> AddressedTurnAction:
    """Ce que le tour fait, une fois la situation classée et la ressource résolue.

    La situation vient du classement de la Slice 07 ; elle n'est **pas**
    redécidée ici. La ressource vient de `resolve_prepared_resource`. Cette
    fonction ne fait que croiser les deux, et elle est pure pour que ce
    croisement soit lisible d'un coup d'œil plutôt qu'éparpillé dans le service.
    """

    if situation is not PresentationSituation.VISUAL_COMMAND:
        return AddressedTurnAction.ASK_BRAIN
    if resolution.verdict is ResourceVerdict.REUSABLE:
        return AddressedTurnAction.SHOW_PREPARED
    if resolution.verdict is ResourceVerdict.AMBIGUOUS:
        return AddressedTurnAction.CLARIFY
    if resolution.verdict is ResourceVerdict.NOT_REQUESTED:
        return AddressedTurnAction.ASK_BRAIN
    return AddressedTurnAction.REFRESH


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------

#: Ordre dans lequel les sections tombent quand le budget est dépassé. Le fil
#: est **le dernier** : c'est la moitié que D06 rend indispensable, et une
#: projection sans parole récente serait précisément le contexte périmé que
#: cette Slice existe pour écarter. Il est raccourci par la tête, jamais vidé
#: tant qu'il reste une entrée.
_DROP_ORDER: tuple[str, ...] = (
    "questions", "entities", "sources", "attention", "claims", "resources", "topics",
)


def build_addressed_turn_context(
    snapshot: object,
    *,
    situation: PresentationSituation,
    evidence: str,
    deictic: str,
    referent: ResolvedReferent | None,
    resource: ResourceResolution,
    budget: int = MAX_ADDRESSED_CONTEXT_CHARS,
) -> AddressedTurnContext:
    """Assembler la projection du tour, bornée.

    **Lève sur deux erreurs de programmation**, et sur rien d'autre : un
    instantané qui n'en est pas un, une situation qui n'est pas typée. Aucune
    donnée de séance ne peut la faire lever — c'est la distinction qui compte,
    et la première version de cette docstring disait « sans jamais lever » deux
    lignes au-dessus de ces deux `raise`. La Slice 09 a livré exactement cette
    phrase et elle lui a coûté un blocage ; le service, lui, rattrape les deux
    et rend un refus typé.

    Le budget est appliqué en retirant des sections entières dans `_DROP_ORDER`,
    puis en raccourcissant le fil par la tête. Ce qui est tombé est **nommé**
    dans `clipped` : une section absente et une section vide ne doivent pas se
    lire pareil, sinon on croit l'ensemble de travail vide alors qu'il est
    seulement trop gros.
    """

    if not isinstance(snapshot, PresentationContextSnapshot):
        raise PresentationAddressedTurnError(
            "addressed_context_snapshot_invalid",
            "La projection d'un tour adressé se construit sur un PresentationContextSnapshot.",
        )
    if not isinstance(situation, PresentationSituation):
        raise PresentationAddressedTurnError(
            "addressed_context_situation_invalid",
            "La situation d'un tour adressé est typée.",
        )
    working_set = snapshot.working_set
    tail = tuple(
        (item.utterance_id, item.sequence, item.text[:MAX_TAIL_ENTRY_CHARS])
        for item in snapshot.tail.entries[-MAX_ADDRESSED_TAIL_ENTRIES:]
    )
    sections: dict[str, tuple] = {
        # Les ressources **vivantes** seulement : une ressource `discardable` a
        # perdu son sujet ou dort depuis dix minutes, et la nommer au cerveau
        # l'inviterait à demander qu'on montre ce que le résolveur refuse.
        "resources": tuple(
            (item.resource_id, item.reference.kind.value, item.reference.title,
             item.topic_id or "", item.temperature.value)
            for item in working_set.resources[-MAX_ADDRESSED_RESOURCES:]
            if item.temperature is not ResourceTemperature.DISCARDABLE
        ),
        "topics": tuple(
            (item.topic_id, item.label) for item in working_set.topics[-MAX_ADDRESSED_TOPICS:]
        ),
        "claims": tuple(
            (item.claim_id, item.statement, item.status.value)
            for item in working_set.claims[-MAX_ADDRESSED_CLAIMS:]
        ),
        "entities": tuple(
            (item.entity_id, item.label) for item in working_set.entities[-MAX_ADDRESSED_ENTITIES:]
        ),
        "sources": tuple(
            (item.source_id, item.title, item.reference)
            for item in working_set.sources[-MAX_ADDRESSED_SOURCES:]
        ),
        "questions": tuple(
            (item.question_id, item.text) for item in working_set.questions[-MAX_ADDRESSED_QUESTIONS:]
        ),
        # `reason` est lu **ici**, sur l'objet en mémoire. C'est la précondition
        # que la Slice 09 a laissée, et c'est le seul endroit du dépôt qui
        # l'exerce : il descend dans `to_brain_context()`, jamais dans
        # `to_trace_payload()`.
        "attention": tuple(
            (item.attention_id, item.category.value, item.severity.value, item.reason)
            for item in working_set.attention[-MAX_ADDRESSED_ATTENTION:]
        ),
    }
    ceiling = budget if isinstance(budget, int) and not isinstance(budget, bool) and budget > 0 else MAX_ADDRESSED_CONTEXT_CHARS
    disposition = policy_for(situation).disposition
    clipped: list[str] = []

    def assemble() -> AddressedTurnContext:
        return AddressedTurnContext(
            session_id=snapshot.session_id or "",
            revision=snapshot.revision,
            situation=situation,
            evidence=str(evidence)[:64],
            disposition=disposition,
            deictic=str(deictic)[:64],
            referent=referent,
            resource=resource,
            tail=tail,
            clipped=tuple(clipped),
            **sections,  # type: ignore[arg-type]
        )

    # Une seule charge utile par pas, et **aucun** objet intermédiaire. La
    # première version rebâtissait le `dataclass` complet *puis* sa charge utile
    # à chaque étape, jusqu'à quinze fois ; `chars` est exactement ce qu'on veut
    # mesurer et rien d'autre ne servait.
    context = assemble()
    payload_chars = context.chars
    for name in _DROP_ORDER:
        if payload_chars <= ceiling:
            return context
        if not sections[name]:
            continue
        sections[name] = ()
        clipped.append(name)
        context = assemble()
        payload_chars = context.chars
    while payload_chars > ceiling and len(tail) > 1:
        tail = tail[1:]
        if "tail" not in clipped:
            clipped.append("tail")
        context = assemble()
        payload_chars = context.chars
    return context


__all__ = [
    "DEFAULT_PREROLL_S",
    "DEICTIC_MARKERS",
    "DEICTIC_PHRASES",
    "MAX_ADDRESSED_ATTENTION",
    "MAX_ADDRESSED_CLAIMS",
    "MAX_ADDRESSED_CONTEXT_CHARS",
    "MAX_ADDRESSED_ENTITIES",
    "MAX_ADDRESSED_QUESTIONS",
    "MAX_ADDRESSED_RESOURCES",
    "MAX_ADDRESSED_SOURCES",
    "MAX_ADDRESSED_TAIL_ENTRIES",
    "MAX_ADDRESSED_TEXT_CHARS",
    "MAX_ADDRESSED_TOPICS",
    "MAX_ADDRESSED_WINDOW_S",
    "MAX_TRIGGER_CLOCK_SKEW_S",
    "AddressedTurnAction",
    "AddressedTurnContext",
    "AddressedWindow",
    "ContextOrigin",
    "PresentationAddressedTurnError",
    "ResolvedReferent",
    "ResourceResolution",
    "ResourceVerdict",
    "build_addressed_turn_context",
    "cited_rank",
    "decide_action",
    "deictic_marker",
    "resolve_prepared_resource",
    "referent_topic_ids",
    "resolve_referent",
]
