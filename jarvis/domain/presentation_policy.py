"""Matrice de manifestation du mode présentation, en données et non en prose.

Une politique écrite dans un prompt n'est pas une politique : elle tient tant
que le modèle la relit, puis elle cède. La Décision 09 exige qu'un tour de
cerveau réussi puisse ne demander *aucune* parole, et la Décision 11 exige que
rien ne se mette à parler spontanément. Les deux sont ici des lignes de table
que le runtime lit (Slice 07), pas des phrases qu'on espère voir respectées.

Vocabulaire réutilisé tel quel :
- `OutputDisposition` (`jarvis/domain/output_disposition.py`) pour les canaux ;
- `SpeechKind` (`jarvis/domain/v2.py`) pour la nature de la parole autorisée —
  c'est déjà ce qui pilote la politique de l'ordonnanceur de parole, en créer
  un second jeu aurait donné deux vérités sur « JARVIS a-t-il le droit de dire
  ça ».

Ce module ne décide rien pour le mode assistant : celui-ci garde son
comportement d'avant (Décision 14), qui n'a jamais eu de matrice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from jarvis.domain.output_disposition import OutputDisposition
from jarvis.domain.v2 import SpeechKind


class PresentationPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


#: Jeu fermé des décisions verrouillées par le handoff
#: `tasks/jarvis-presentation-interaction-mode/docs/01-decision-log.md`.
#: Une ligne de politique doit citer une décision qui existe vraiment : sans
#: cette liste, `("Dfromage",)` passait, et le champ ne prouvait plus rien.
#: L'étendre suppose d'abord d'ajouter la décision au journal.
LOCKED_DECISIONS: frozenset[str] = frozenset(f"D{index:02d}" for index in range(1, 15))


class PresentationSituation(StrEnum):
    """Les situations que le mode présentation sait distinguer. Fermé en V1."""

    #: Parole captée dans la salle, qui ne s'adressait pas à JARVIS.
    AMBIENT_OBSERVATION = "ambient_observation"
    #: Tour adressé demandant de montrer, ouvrir, déplacer, préparer.
    VISUAL_COMMAND = "visual_command"
    #: Tour adressé posant une vraie question, dont la réponse a de la valeur dite.
    KNOWLEDGE_QUESTION = "knowledge_question"
    #: Tour adressé demandant explicitement à JARVIS de parler.
    EXPLICIT_SPEAK_REQUEST = "explicit_speak_request"
    #: Une commande a abouti.
    COMMAND_CONFIRMATION = "command_confirmation"
    #: Une commande a échoué.
    COMMAND_ERROR = "command_error"
    #: Contradiction ou écart relevé par la vérification de fond.
    FACT_CHECK_ATTENTION = "fact_check_attention"


@dataclass(frozen=True, slots=True)
class PresentationOutputPolicy:
    """Une ligne de la matrice. Lisible par le runtime, vérifiée par des tests."""

    situation: PresentationSituation
    #: Ce que le tour manifeste si rien d'autre n'est demandé.
    disposition: OutputDisposition
    #: Plafond, pas défaut : faux interdit toute parole, même demandée.
    voice_allowed: bool
    #: La situation naît-elle d'un tour explicitement adressé (Décisions 03, 05) ?
    requires_explicit_address: bool
    #: La situation peut-elle autoriser une action visible ou persistante (Décision 03) ?
    authorizes_action: bool
    #: Natures de parole admissibles quand `voice_allowed`.
    speech_kinds: tuple[SpeechKind, ...]
    #: Natures admissibles **malgré** le plafond, parce que les taire créerait
    #: le défaut que ce module existe pour interdire.
    #:
    #: Le plafond de `voice_allowed` reste absolu pour tout le reste : ces
    #: natures-ci sont nommées une par une dans la donnée, et validées comme
    #: les autres. C'est la différence entre une exception écrite dans la
    #: matrice et une exception posée par-dessus : `may_speak` reste la vérité
    #: entière, et une ligne ajoutée plus tard ne peut pas ouvrir une brèche
    #: sans passer par `__post_init__`.
    #:
    #: Deux natures seulement, chacune pour une raison mesurée :
    #: - `ERROR` — une panne muette est un défaut, pas de la discrétion. La
    #:   Décision 09 dit « normalement » silencieux, pas « quoi qu'il arrive ».
    #: - `QUESTION` — la clarification requise. Une commande visuelle que
    #:   JARVIS ne sait pas résoudre et dont il ne peut pas demander le sens se
    #:   termine sans écran **et** sans phrase, et l'utilisateur ne sait même
    #:   pas qu'il doit redemander. Ce n'est plus une commande visuelle
    #:   *aboutie* : même raisonnement que `COMMAND_ERROR`, qui existe déjà
    #:   parce que l'issue, et non l'étiquette, change la situation.
    #: `kw_only` pour rester déclarée à côté de `speech_kinds`, qu'elle
    #: complète, sans imposer un défaut aux champs qui suivent.
    safety_speech_kinds: tuple[SpeechKind, ...] = field(default=(), kw_only=True)
    #: La situation peut-elle lever le signal discret d'attention (Décision 11) ?
    may_raise_attention_cue: bool
    #: Décisions verrouillées dont cette ligne est la mise en oeuvre.
    decisions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.situation, PresentationSituation) or not isinstance(self.disposition, OutputDisposition):
            raise PresentationPolicyError("presentation_policy_invalid", "Policy rows are typed")
        if any(type(getattr(self, name)) is not bool for name in
               ("voice_allowed", "requires_explicit_address", "authorizes_action", "may_raise_attention_cue")):
            raise PresentationPolicyError("presentation_policy_invalid", "Policy flags must be booleans")
        for name in ("speech_kinds", "safety_speech_kinds"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(not isinstance(kind, SpeechKind) for kind in value):
                raise PresentationPolicyError("presentation_policy_invalid", f"{name} must be typed SpeechKind values")
        if not isinstance(self.decisions, tuple) or not self.decisions:
            raise PresentationPolicyError("presentation_policy_unjustified", "A policy row names the decisions it implements")
        if any(ref not in LOCKED_DECISIONS for ref in self.decisions):
            raise PresentationPolicyError("presentation_policy_unjustified",
                                          f"Unknown decision reference in {self.decisions}")
        # Invariants portés par la donnée elle-même, pour qu'une ligne ajoutée
        # plus tard ne puisse pas contredire les décisions en silence.
        if self.disposition.speaks and not self.voice_allowed:
            raise PresentationPolicyError("presentation_policy_invalid", "A speaking default needs voice_allowed")
        if bool(self.speech_kinds) is not self.voice_allowed:
            raise PresentationPolicyError("presentation_policy_invalid", "speech_kinds exist exactly when voice is allowed")
        if self.voice_allowed and not self.requires_explicit_address:
            raise PresentationPolicyError("presentation_policy_spontaneous_speech",
                                          "V1 never speaks without an explicit address (D11)")
        if self.authorizes_action and not self.requires_explicit_address:
            raise PresentationPolicyError("presentation_policy_ambient_authority",
                                          "Ambient speech never authorizes an action (D03)")
        if self.safety_speech_kinds and not self.requires_explicit_address:
            # Même barrière que `voice_allowed` : une exception de sûreté reste
            # de la parole, et rien ne parle sans adressage explicite (D03, D11).
            raise PresentationPolicyError("presentation_policy_spontaneous_speech",
                                          "A safety exception is still speech, and still needs an explicit address")
        if set(self.safety_speech_kinds) & set(self.speech_kinds):
            # Deux vérités sur la même nature : la ligne dirait à la fois
            # « elle passe par le plafond » et « elle le contourne ».
            raise PresentationPolicyError("presentation_policy_invalid",
                                          "A kind is either allowed by the ceiling or an exception to it, never both")
        if len(set(self.safety_speech_kinds)) != len(self.safety_speech_kinds):
            raise PresentationPolicyError("presentation_policy_invalid", "safety_speech_kinds has a duplicate")


PRESENTATION_POLICY: Mapping[PresentationSituation, PresentationOutputPolicy] = MappingProxyType({
    policy.situation: policy for policy in (
        # Écouter n'est pas obéir, et n'est pas non plus une raison de parler.
        PresentationOutputPolicy(
            situation=PresentationSituation.AMBIENT_OBSERVATION,
            disposition=OutputDisposition.SILENT, voice_allowed=False,
            requires_explicit_address=False, authorizes_action=False,
            speech_kinds=(), may_raise_attention_cue=False, decisions=("D03", "D11"),
        ),
        # Montrer, sans commenter : l'écran répond, la voix se tait.
        PresentationOutputPolicy(
            situation=PresentationSituation.VISUAL_COMMAND,
            disposition=OutputDisposition.VISUAL_ONLY, voice_allowed=False,
            requires_explicit_address=True, authorizes_action=True,
            speech_kinds=(), safety_speech_kinds=(SpeechKind.ERROR, SpeechKind.QUESTION),
            may_raise_attention_cue=False, decisions=("D09",),
        ),
        # Une vraie question mérite une vraie réponse dite, appuyée si besoin
        # par ce qui est déjà préparé à l'écran.
        PresentationOutputPolicy(
            situation=PresentationSituation.KNOWLEDGE_QUESTION,
            disposition=OutputDisposition.VISUAL_AND_VOICE, voice_allowed=True,
            requires_explicit_address=True, authorizes_action=True,
            speech_kinds=(SpeechKind.QUESTION, SpeechKind.RESULT),
            safety_speech_kinds=(SpeechKind.ERROR,),
            may_raise_attention_cue=False, decisions=("D10",),
        ),
        # On a demandé des mots : on donne des mots, sans saisir l'écran du
        # présentateur au passage.
        PresentationOutputPolicy(
            situation=PresentationSituation.EXPLICIT_SPEAK_REQUEST,
            disposition=OutputDisposition.VOICE_ONLY, voice_allowed=True,
            requires_explicit_address=True, authorizes_action=True,
            speech_kinds=(SpeechKind.ACK, SpeechKind.PROGRESS, SpeechKind.QUESTION,
                          SpeechKind.RESULT, SpeechKind.ERROR),
            may_raise_attention_cue=False, decisions=("D05", "D10"),
        ),
        # Une réussite se constate à l'écran. Ligne distincte de l'échec, et
        # pas une convention d'appelant : tant que les deux issues partageaient
        # une ligne, « une réussite ne s'annonce pas » ne tenait que si le
        # runtime pensait à ne pas demander la parole. C'est précisément ce que
        # ce module existe pour rendre impossible.
        PresentationOutputPolicy(
            situation=PresentationSituation.COMMAND_CONFIRMATION,
            disposition=OutputDisposition.VISUAL_ONLY, voice_allowed=False,
            requires_explicit_address=True, authorizes_action=True,
            speech_kinds=(), safety_speech_kinds=(SpeechKind.ERROR, SpeechKind.QUESTION),
            may_raise_attention_cue=False, decisions=("D09",),
        ),
        # Un échec se constate aussi, plus le signal discret, et peut se dire
        # si le tour le demande : un échec silencieux est un défaut, pas de la
        # discrétion.
        PresentationOutputPolicy(
            situation=PresentationSituation.COMMAND_ERROR,
            disposition=OutputDisposition.VISUAL_ONLY, voice_allowed=True,
            requires_explicit_address=True, authorizes_action=True,
            speech_kinds=(SpeechKind.ERROR,), safety_speech_kinds=(SpeechKind.QUESTION,),
            may_raise_attention_cue=True, decisions=("D09", "D11"),
        ),
        # Contredire quelqu'un à voix haute devant son public n'arrivera pas en
        # V1 : un voyant, un son bref, et l'humain décide.
        PresentationOutputPolicy(
            situation=PresentationSituation.FACT_CHECK_ATTENTION,
            disposition=OutputDisposition.VISUAL_ONLY, voice_allowed=False,
            requires_explicit_address=False, authorizes_action=False,
            speech_kinds=(), may_raise_attention_cue=True, decisions=("D11",),
        ),
    )
})


#: Natures admissibles pour une parole qui ne se rattache à **aucun tour
#: adressé connu** : un relais spontané de fin de sous-agent, une notification.
#:
#: Il n'existe pas de ligne de matrice pour cela — il n'y a pas de situation,
#: justement. La règle vit donc ici, nommée, plutôt que dans une branche de
#: `if` au fond du runtime où personne ne la relirait. Elle dit la même chose
#: que `safety_speech_kinds` sans adressage du tout : ce qui est cassé
#: s'entend, même pendant une présentation, et rien d'autre ne parle.
#:
#: `QUESTION` n'en fait délibérément pas partie : sans tour adressé, il n'y a
#: rien à clarifier.
UNADDRESSED_SAFETY_KINDS: tuple[SpeechKind, ...] = (SpeechKind.ERROR,)


def policy_for(situation: PresentationSituation) -> PresentationOutputPolicy:
    """Ligne applicable. `KeyError` sur une situation inconnue est voulu : une
    situation non couverte doit être ajoutée à la matrice, pas devinée.

    Nommée `policy_for` et non `presentation_policy` : une fonction homonyme de
    son propre module rend `from jarvis.domain import presentation_policy` et
    `from jarvis.domain.presentation_policy import presentation_policy`
    silencieusement différents.
    """
    return PRESENTATION_POLICY[situation]


def may_speak(situation: PresentationSituation, kind: SpeechKind) -> bool:
    """La parole de cette nature est-elle admissible dans cette situation ?

    Vérité **entière** : le plafond et ses exceptions sont tous deux de la
    donnée de la ligne, donc il n'existe pas de second endroit où lire « JARVIS
    a-t-il le droit de dire ça ». Une couche posée au-dessus de cette fonction
    serait exactement la prose qu'on a voulu abolir, réécrite en Python.
    """
    policy = PRESENTATION_POLICY[situation]
    if kind in policy.safety_speech_kinds:
        return True
    return policy.voice_allowed and kind in policy.speech_kinds
