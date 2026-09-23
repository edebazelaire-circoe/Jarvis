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

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from jarvis.domain.output_disposition import OutputDisposition
from jarvis.domain.v2 import SpeechKind


class PresentationPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    #: Issue d'une commande : elle a abouti, ou elle a échoué.
    CONFIRMATION_OR_ERROR = "confirmation_or_error"
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
        if not isinstance(self.speech_kinds, tuple) or any(not isinstance(kind, SpeechKind) for kind in self.speech_kinds):
            raise PresentationPolicyError("presentation_policy_invalid", "speech_kinds must be typed SpeechKind values")
        if not self.decisions or any(not isinstance(ref, str) or not ref.strip() for ref in self.decisions):
            raise PresentationPolicyError("presentation_policy_unjustified", "A policy row names the decisions it implements")
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

    def to_dict(self) -> dict[str, object]:
        return {
            "situation": self.situation.value, "disposition": self.disposition.value,
            "voice_allowed": self.voice_allowed, "requires_explicit_address": self.requires_explicit_address,
            "authorizes_action": self.authorizes_action,
            "speech_kinds": [kind.value for kind in self.speech_kinds],
            "may_raise_attention_cue": self.may_raise_attention_cue, "decisions": list(self.decisions),
        }


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
            speech_kinds=(), may_raise_attention_cue=False, decisions=("D09",),
        ),
        # Une vraie question mérite une vraie réponse dite, appuyée si besoin
        # par ce qui est déjà préparé à l'écran.
        PresentationOutputPolicy(
            situation=PresentationSituation.KNOWLEDGE_QUESTION,
            disposition=OutputDisposition.VISUAL_AND_VOICE, voice_allowed=True,
            requires_explicit_address=True, authorizes_action=True,
            speech_kinds=(SpeechKind.QUESTION, SpeechKind.RESULT),
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
        # Une réussite se constate à l'écran. Un échec aussi, plus le signal
        # discret : un échec silencieux est un défaut, pas de la discrétion.
        PresentationOutputPolicy(
            situation=PresentationSituation.CONFIRMATION_OR_ERROR,
            disposition=OutputDisposition.VISUAL_ONLY, voice_allowed=True,
            requires_explicit_address=True, authorizes_action=True,
            speech_kinds=(SpeechKind.ERROR,), may_raise_attention_cue=True,
            decisions=("D09", "D11"),
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


def presentation_policy(situation: PresentationSituation) -> PresentationOutputPolicy:
    """Ligne applicable. `KeyError` sur une situation inconnue est voulu : une
    situation non couverte doit être ajoutée à la matrice, pas devinée."""
    return PRESENTATION_POLICY[situation]


def may_speak(situation: PresentationSituation, kind: SpeechKind) -> bool:
    """La parole de cette nature est-elle admissible dans cette situation ?"""
    policy = PRESENTATION_POLICY[situation]
    return policy.voice_allowed and kind in policy.speech_kinds
