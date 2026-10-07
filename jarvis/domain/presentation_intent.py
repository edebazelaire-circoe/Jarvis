"""Intention de sortie du mode présentation : ce qu'un tour veut manifester.

Handoff `jarvis-presentation-interaction-mode` (2026-10), Slice 07 (décisions
A3, R4). La matrice (`presentation_policy.py`) dit ce qu'une **situation** a le
droit de manifester ; cette valeur dit ce qu'un **tour précis** demande, sous
une forme sémantique qu'un puits d'affichage consomme
(`jarvis/core/presentation_display.py`). Aujourd'hui le puits est la voie
directe vers la scène ; demain ce sera le Tool Brain (Slice 08). L'intention ne
change pas quand l'adaptateur change : c'est tout son objet.

Vocabulaire réutilisé, aucun nouveau jeu de parole
--------------------------------------------------

Les noms du handoff (doc 02 §7) sont reconnus ici, une fois, pour qu'aucun
second vocabulaire ne naisse à côté du premier :

- `kind` du handoff → `situation: PresentationSituation` (la matrice) ;
- `speech` du handoff (`none|concise|normal`) → `disposition: OutputDisposition`
  plus `speech_ceiling: tuple[SpeechKind, ...]`, borné par `may_speak` sur la
  ligne de la matrice. Il n'existe **pas** d'énumération `concise|normal` ;
- `display` du handoff → `DisplayIntent{semantic: DisplaySemantic,
  resource_refs}` ;
- `urgency` du handoff → `IntentUrgency{immediate, soon, opportunistic}`.

Seules `DisplaySemantic` et `IntentUrgency` sont nouvelles, parce qu'aucune
énumération existante ne dit « révéler une ressource préparée » ni « quand ».

Ce qui n'entre jamais ici
-------------------------

Aucune parole. `context_refs` porte au plus huit **identifiants** (énonciation,
ressource, attention, affirmation…), jamais un libellé ni une phrase : un
identifiant sans espace, borné à 64 caractères. `reason` est un code stable.
L'intention part au journal telle quelle (`to_trace_payload`), donc elle ne
peut rien porter que le journal n'a pas le droit de lire.

`authorizes_actions` est figé à faux (D03) : une intention est une demande de
manifestation, jamais un ordre. Le puits reste juge de ce qu'il fait, et la
scène reste juge du reste (D12).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

from jarvis.domain.output_disposition import OutputDisposition
from jarvis.domain.presentation_addressed_turn import AddressedTurnAction
from jarvis.domain.presentation_attention import PresentationAttention, attention_output_policy
from jarvis.domain.presentation_policy import PresentationSituation, may_speak, policy_for
from jarvis.domain.v2 import SpeechKind

__all__ = [
    "MAX_INTENT_CONTEXT_REFS",
    "MAX_INTENT_REF_CHARS",
    "DisplayIntent",
    "DisplaySemantic",
    "IntentUrgency",
    "PresentationIntentError",
    "PresentationOutputIntent",
    "intent_for_attention",
    "intent_for_plan",
]

#: Références de contexte qu'une intention porte au plus. Assez pour nommer le
#: référent, la ressource, ses égales et quelques sources ; trop peu pour
#: qu'une intention devienne une projection de contexte bis.
MAX_INTENT_CONTEXT_REFS = 8

#: Longueur d'un identifiant porté. Même borne que `MAX_PRESENTATION_ID_CHARS`
#: (ensemble de travail) et que les lignes de journal de la voie adressée.
MAX_INTENT_REF_CHARS = 64

#: Longueur d'un code (`reason`). Un code, pas une phrase.
MAX_INTENT_REASON_CHARS = 64

#: Longueur gardée de la corrélation. **Entière** jusqu'à cette borne (leçon F1
#: de la Slice 04 : une corrélation réelle de la voie cerveau fait 72
#: caractères) ; seule la trace la coupe.
MAX_INTENT_CORRELATION_CHARS = 256


class PresentationIntentError(ValueError):
    """Refus typé, code stable et anglais, message pour un humain francophone."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DisplaySemantic(StrEnum):
    """Ce que l'écran doit faire, en sens et non en outil.

    Aucun nom d'outil, aucune géométrie : choisir `scene_update_object` ou une
    fenêtre de prefab appartient au puits (Slice 08 pour le Tool Brain).
    """

    #: Rendre visible une ressource déjà préparée et montée masquée.
    REVEAL_PREPARED = "reveal_prepared"
    #: Faire voir un point d'attention (contradiction relevée), discrètement.
    SHOW_ATTENTION = "show_attention"


class IntentUrgency(StrEnum):
    """Quand la manifestation compte. Une donnée pour le puits, pas un délai."""

    #: Le présentateur attend une réaction : un tour adressé qui montre ou demande.
    IMMEDIATE = "immediate"
    #: Utile bientôt, sans bloquer : la réponse du cerveau, un point d'attention.
    SOON = "soon"
    #: Quand l'occasion se présente : une re-préparation qui servira plus tard.
    OPPORTUNISTIC = "opportunistic"


def _ref(name: str, value: object) -> str:
    """Un identifiant, pas un texte : non vide, borné, **sans aucun espace**.

    Plus strict que `presentation_id` (qui tolère un espace intérieur) : une
    phrase de salle contient des espaces, un identifiant n'en contient pas.
    C'est la règle qui fait de « jamais de texte » une propriété du type.
    """

    if not isinstance(value, str) or not value or len(value) > MAX_INTENT_REF_CHARS:
        raise PresentationIntentError(
            "presentation_intent_ref_invalid",
            f"{name} doit être un identifiant non vide d'au plus {MAX_INTENT_REF_CHARS} caractères",
        )
    if any(char.isspace() for char in value) or not value.isprintable():
        raise PresentationIntentError(
            "presentation_intent_ref_text",
            f"{name} ressemble à du texte : un identifiant ne contient aucun espace",
        )
    return value


@dataclass(frozen=True, slots=True)
class DisplayIntent:
    """La moitié visuelle d'une intention : un sens, et les ressources visées."""

    semantic: DisplaySemantic
    resource_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.semantic, DisplaySemantic):
            raise PresentationIntentError("presentation_intent_invalid", "semantic est typé")
        if not isinstance(self.resource_refs, tuple) or not self.resource_refs:
            # Un affichage qui ne vise rien n'est pas un affichage : le puits
            # devrait deviner quoi montrer, et c'est exactement ce qu'il ne fait pas.
            raise PresentationIntentError(
                "presentation_intent_display_empty", "Un affichage nomme ce qu'il montre"
            )
        if len(self.resource_refs) > MAX_INTENT_CONTEXT_REFS:
            raise PresentationIntentError(
                "presentation_intent_refs_overflow",
                f"Au plus {MAX_INTENT_CONTEXT_REFS} ressources visées",
            )
        for item in self.resource_refs:
            _ref("resource_refs", item)

    def to_trace_payload(self) -> dict[str, Any]:
        return {"semantic": self.semantic.value, "resource_refs": list(self.resource_refs)}


@dataclass(frozen=True, slots=True)
class PresentationOutputIntent:
    """Ce qu'un tour demande de manifester. Sémantique, bornée, sans parole.

    Les invariants sont portés par la donnée, comme ceux de la matrice : une
    intention ne peut pas demander une parole que la ligne de sa situation
    refuse (`may_speak`), ni un affichage sous une disposition qui ne montre
    rien.
    """

    situation: PresentationSituation
    disposition: OutputDisposition
    display: DisplayIntent | None
    urgency: IntentUrgency
    #: Code stable : pourquoi cette intention. Jamais une phrase.
    reason: str
    #: Natures de parole que ce tour **peut** produire. Un plafond, pas une
    #: commande : la porte de parole (`PresentationSpeechGate`) reste seule à
    #: admettre une phrase réelle.
    speech_ceiling: tuple[SpeechKind, ...] = ()
    #: Au plus huit identifiants. Jamais de texte.
    context_refs: tuple[str, ...] = ()
    correlation_id: str = ""

    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not isinstance(self.situation, PresentationSituation):
            raise PresentationIntentError("presentation_intent_invalid", "situation est typée")
        if not isinstance(self.disposition, OutputDisposition):
            raise PresentationIntentError("presentation_intent_invalid", "disposition est typée")
        if not isinstance(self.urgency, IntentUrgency):
            raise PresentationIntentError("presentation_intent_invalid", "urgency est typée")
        if self.display is not None and not isinstance(self.display, DisplayIntent):
            raise PresentationIntentError("presentation_intent_invalid", "display est typé")
        if self.display is not None and not self.disposition.shows:
            raise PresentationIntentError(
                "presentation_intent_display_hidden",
                "Un affichage demandé sous une disposition qui ne montre rien",
            )
        if not isinstance(self.reason, str) or not self.reason or len(self.reason) > MAX_INTENT_REASON_CHARS \
                or any(char.isspace() for char in self.reason):
            raise PresentationIntentError("presentation_intent_reason_invalid", "reason est un code")
        if not isinstance(self.speech_ceiling, tuple) or any(
            not isinstance(kind, SpeechKind) for kind in self.speech_ceiling
        ):
            raise PresentationIntentError("presentation_intent_invalid", "speech_ceiling est typé")
        for kind in self.speech_ceiling:
            if not may_speak(self.situation, kind):
                # La matrice est la vérité entière (Slice 07 de 2026-09) : une
                # intention ne l'élargit pas, elle la lit.
                raise PresentationIntentError(
                    "presentation_intent_speech_beyond_policy",
                    f"{kind.value} n'est pas admissible en {self.situation.value}",
                )
        if bool(self.speech_ceiling) is not self.disposition.speaks:
            raise PresentationIntentError(
                "presentation_intent_invalid",
                "Un plafond de parole existe exactement quand la disposition parle",
            )
        if not isinstance(self.context_refs, tuple) or len(self.context_refs) > MAX_INTENT_CONTEXT_REFS:
            raise PresentationIntentError(
                "presentation_intent_refs_overflow",
                f"Au plus {MAX_INTENT_CONTEXT_REFS} références de contexte",
            )
        for item in self.context_refs:
            _ref("context_refs", item)
        if not isinstance(self.correlation_id, str) or len(self.correlation_id) > MAX_INTENT_CORRELATION_CHARS:
            raise PresentationIntentError("presentation_intent_invalid", "correlation_id est borné")

    def to_trace_payload(self) -> dict[str, Any]:
        """Identifiants et codes seulement : c'est ce qui part au journal."""

        return {
            "situation": self.situation.value,
            "disposition": self.disposition.value,
            "display": None if self.display is None else self.display.to_trace_payload(),
            "urgency": self.urgency.value,
            "reason": self.reason,
            "speech_ceiling": [kind.value for kind in self.speech_ceiling],
            "context_refs": list(self.context_refs),
            "correlation_id": self.correlation_id[:MAX_INTENT_REF_CHARS] or None,
            "authorizes_actions": self.authorizes_actions,
        }


def _bounded_refs(*values: object) -> tuple[str, ...]:
    """Dédoublonnées, dans l'ordre, coupées à huit.

    Une valeur qui n'a pas la forme d'un identifiant (vide, trop longue, avec
    un espace) est **écartée** plutôt que de faire lever le constructeur : une
    référence de contexte est un indice, et un indice manquant ne doit pas
    priver le tour de son intention. L'identifiant que l'affichage vise, lui,
    passe par `_ref` et lève : sans lui il n'y a rien à montrer.
    """

    seen: list[str] = []
    for value in values:
        try:
            ref = _ref("context_refs", value)
        except PresentationIntentError:
            continue
        if ref not in seen:
            seen.append(ref)
    return tuple(seen[:MAX_INTENT_CONTEXT_REFS])


def intent_for_plan(plan: object, outcome: object | None = None) -> PresentationOutputIntent:
    """L'intention d'un tour adressé, à partir de son plan (et de son issue).

    `plan` est un `AddressedTurnPlan` (`jarvis/core/presentation_addressed_turn.py`),
    lu par ses attributs : le domaine n'importe pas le cœur. `outcome`, quand
    il est donné, est un `AddressedTurnOutcome` dont l'action **remplace**
    celle du plan — une révélation refusée devient un rafraîchissement, et
    l'intention doit dire ce qui s'est fait, pas ce qui était prévu.

    Une action par ligne, sans cascade cachée :

    | action | display | disposition | plafond | urgence |
    | --- | --- | --- | --- | --- |
    | `show_prepared` | `reveal_prepared` | `visual_only` | — | `immediate` |
    | `clarify` | — | `voice_only` | `question` | `immediate` |
    | `refresh` | — | `silent` | — | `opportunistic` |
    | `ask_brain` | — | ligne de la matrice | ligne de la matrice | `soon` |
    """

    context = getattr(plan, "context", None)
    situation = getattr(plan, "situation", None)
    action = getattr(plan, "action", None)
    if outcome is not None:
        action = getattr(outcome, "action", action)
    if not isinstance(situation, PresentationSituation) or not isinstance(action, AddressedTurnAction) \
            or context is None:
        raise PresentationIntentError("presentation_intent_plan_invalid", "Le plan n'est pas un plan adressé")
    resource = getattr(context, "resource", None)
    referent = getattr(context, "referent", None)
    resource_id = str(getattr(resource, "resource_id", "") or "")
    refs = _bounded_refs(
        getattr(referent, "utterance_id", ""),
        resource_id,
        *tuple(getattr(resource, "tied", ()) or ()),
    )
    correlation_id = str(getattr(plan, "correlation_id", "") or "")
    if action is AddressedTurnAction.SHOW_PREPARED:
        if not resource_id:
            raise PresentationIntentError(
                "presentation_intent_plan_invalid", "Montrer suppose une ressource retenue"
            )
        return PresentationOutputIntent(
            situation=situation, disposition=OutputDisposition.VISUAL_ONLY,
            display=DisplayIntent(DisplaySemantic.REVEAL_PREPARED, (resource_id,)),
            urgency=IntentUrgency.IMMEDIATE, reason="addressed_show_prepared",
            context_refs=refs, correlation_id=correlation_id,
        )
    if action is AddressedTurnAction.CLARIFY:
        return PresentationOutputIntent(
            situation=situation, disposition=OutputDisposition.VOICE_ONLY, display=None,
            urgency=IntentUrgency.IMMEDIATE, reason="addressed_clarify",
            speech_ceiling=(SpeechKind.QUESTION,), context_refs=refs,
            correlation_id=correlation_id,
        )
    if action is AddressedTurnAction.REFRESH:
        return PresentationOutputIntent(
            situation=situation, disposition=OutputDisposition.SILENT, display=None,
            urgency=IntentUrgency.OPPORTUNISTIC, reason="addressed_refresh",
            context_refs=refs, correlation_id=correlation_id,
        )
    row = policy_for(situation)
    return PresentationOutputIntent(
        situation=situation, disposition=row.disposition, display=None,
        urgency=IntentUrgency.SOON, reason="addressed_ask_brain",
        speech_ceiling=row.speech_kinds if row.disposition.speaks else (),
        context_refs=refs, correlation_id=correlation_id,
    )


def intent_for_attention(attention: PresentationAttention) -> PresentationOutputIntent:
    """L'intention d'un point d'attention : visuelle seulement, jamais de parole (D11).

    La disposition et le plafond sont **lus** sur la ligne `FACT_CHECK_ATTENTION`
    (`attention_output_policy()`), pas recopiés : si la matrice changeait, ce
    constructeur suivrait — ou lèverait, si elle se mettait à parler sans
    adressage, ce que la matrice refuse déjà de construire.
    """

    if not isinstance(attention, PresentationAttention):
        raise PresentationIntentError(
            "presentation_intent_attention_invalid", "Seule une attention typée se manifeste"
        )
    row = attention_output_policy()
    return PresentationOutputIntent(
        situation=row.situation, disposition=row.disposition,
        display=DisplayIntent(DisplaySemantic.SHOW_ATTENTION, (_ref("attention_id", attention.attention_id),)),
        urgency=IntentUrgency.SOON, reason="fact_check_attention",
        speech_ceiling=row.speech_kinds,
        context_refs=_bounded_refs(
            attention.attention_id, attention.claim_id, attention.topic_id or "",
            *(piece.source_id for piece in attention.evidence),
        ),
    )
