"""Port d'affichage du mode présentation : où part une intention de sortie.

Handoff `jarvis-presentation-interaction-mode` (2026-10), Slice 07 (A3, R4).

`PresentationDisplaySink` est un port **possédé par son consommateur**, comme
`HiddenSceneStager` (`core/presentation_speculative.py`) : le cœur dit ce dont
il a besoin, un adaptateur du runtime le réalise. L'adaptateur d'aujourd'hui est
la voie directe vers la scène (`runtime/presentation_display_sink.py`
› `DirectSceneDisplaySink`). Celui de la Slice 08 sera le Tool Brain, échangé
dans `PresentationComposition.build` sans toucher à ce module ni à
`domain/presentation_intent.py` (R5) : `withdraw_speculative` y deviendra
l'annulation du Tool Brain.

`PresentationDisplayPublisher` est la mince couche que le service du tour
adressé tient devant n'importe quel puits. Elle ne décide rien. Elle écrit
`presentation.intent.published` **avant** de remettre l'intention au puits —
c'est ce qui rend lisible, dans la trace, l'ordre « intention puis effet » que
la Slice 08 devra conserver — puis le reçu, ou la panne. Identifiants et codes
seulement : `PresentationOutputIntent.to_trace_payload()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from jarvis.domain.presentation_intent import PresentationOutputIntent
from jarvis.ports.v2 import DiagnosticSink

__all__ = [
    "ALLOWED_IMPORT_CLOSURE",
    "INTENT_KIND",
    "DisplayReceipt",
    "PresentationDisplayPublisher",
    "PresentationDisplaySink",
]

#: Préfixe des lignes de journal de ce port.
INTENT_KIND = "presentation.intent"

#: Recopie maximale d'un code dans une ligne. Même borne que la voie adressée.
_MAX_CODE_CHARS = 64


@dataclass(frozen=True, slots=True)
class DisplayReceipt:
    """Réponse typée d'un puits. Jamais une exception attendue, toujours une valeur.

    `code` est le code stable du puits ; `detail` la disposition propre à
    l'adaptateur (pour la voie directe, l'admission de la voie spéculative),
    elle aussi un code. Aucun des deux n'est une phrase.
    """

    delivered: bool
    code: str
    detail: str = ""

    def to_trace_payload(self) -> dict[str, Any]:
        return {
            "delivered": self.delivered,
            "receipt": str(self.code)[:_MAX_CODE_CHARS],
            "detail": str(self.detail)[:_MAX_CODE_CHARS] or None,
        }


@runtime_checkable
class PresentationDisplaySink(Protocol):
    """Ce que le mode présentation demande à qui exécute l'affichage."""

    async def publish(self, intent: PresentationOutputIntent) -> DisplayReceipt:
        """Exécuter la partie visuelle de l'intention. Rend un reçu."""

    def withdraw_speculative(self, reason: str) -> int:
        """Retirer ce qui attend encore d'être montré sans avoir été demandé.

        Synchrone : appelé depuis `arm()`, qui ne cède jamais la boucle (D04).
        Rend le nombre d'intentions retirées.
        """


class PresentationDisplayPublisher:
    """Trace l'intention, puis la remet au puits. Rien d'autre."""

    __slots__ = ("_sink", "_diagnostics", "diagnostic_failures")

    def __init__(self, sink: PresentationDisplaySink, *, diagnostics: DiagnosticSink | None = None) -> None:
        self._sink = sink
        self._diagnostics = diagnostics
        #: Lignes perdues par un journal en panne. Comptées, jamais seulement avalées.
        self.diagnostic_failures = 0

    @property
    def sink_name(self) -> str:
        return type(self._sink).__name__[:_MAX_CODE_CHARS]

    async def publish(self, intent: PresentationOutputIntent) -> DisplayReceipt:
        """Publier. La panne du puits est dite, puis **relevée** à l'appelant.

        Relevée et non convertie en reçu : l'appelant (le tour adressé) a déjà
        un chemin nommé pour une révélation qui lève (`addressed_reveal_failed`
        → rafraîchir), et un second endroit qui déciderait du repli serait une
        seconde vérité.
        """

        base = {"sink": self.sink_name, **intent.to_trace_payload()}
        self._emit("published", "Intention de sortie publiée vers le puits d'affichage",
                   data={"code": "presentation_intent_published", **base})
        try:
            receipt = await self._sink.publish(intent)
        except Exception as exc:
            self._emit("failed", "Le puits d'affichage a levé sur une intention",
                       level="error",
                       data={"code": "presentation_intent_failed", "sink": self.sink_name,
                             "reason": intent.reason, "error_class": type(exc).__name__})
            raise
        if not isinstance(receipt, DisplayReceipt):
            # Un puits hors contrat ne passe pas pour un puits qui a montré.
            receipt = DisplayReceipt(False, "presentation_intent_receipt_untyped",
                                     detail=type(receipt).__name__)
        self._emit("receipt",
                   "Intention de sortie servie par le puits" if receipt.delivered
                   else "Intention de sortie refusée par le puits",
                   level="info" if receipt.delivered else "warning",
                   data={"code": "presentation_intent_receipt", "sink": self.sink_name,
                         "reason": intent.reason, **receipt.to_trace_payload()})
        return receipt

    def withdraw_speculative(self, reason: str) -> int:
        """Retirer, compter, dire. Ne lève jamais : `arm()` ne doit pas casser."""

        code = str(reason)[:_MAX_CODE_CHARS]
        try:
            count = self._sink.withdraw_speculative(code)
        except Exception as exc:  # noqa: BLE001 - un retrait raté ne retarde pas un tour adressé
            self._emit("withdraw_failed", "Retrait des intentions spéculatives en échec",
                       level="error",
                       data={"code": "presentation_intent_withdraw_failed", "sink": self.sink_name,
                             "reason": code, "error_class": type(exc).__name__})
            return 0
        count = count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else 0
        self._emit("withdrawn", "Intentions spéculatives retirées pour un tour explicite",
                   data={"code": "presentation_intent_withdrawn", "sink": self.sink_name,
                         "reason": code, "withdrawn": count})
        return count

    def _emit(self, event: str, message: str, *, level: str = "info", data: dict[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"{INTENT_KIND}.{event}", message, level=level, data=data)
        except Exception:  # noqa: BLE001 - un journal en panne ne décide pas d'un affichage
            self.diagnostic_failures += 1


#: Ce que ce module charge réellement, mesuré et **fermé** (même garde que
#: `core/presentation_attention.py`). Du domaine, des ports, et ce module :
#: ni `jarvis.runtime.*`, ni la scène (`jarvis.domain.scene`,
#: `runtime/display_mcp.py`), ni aucun autre `jarvis.core.*`. Le port ne sait
#: pas qui affiche ; c'est la condition pour que la Slice 08 change
#: d'adaptateur sans le toucher.
ALLOWED_IMPORT_CLOSURE: frozenset[str] = frozenset(
    {
        "jarvis",
        "jarvis.core",
        "jarvis.core.presentation_display",
        "jarvis.domain",
        "jarvis.domain._checks",
        "jarvis.domain.back_brain",
        "jarvis.domain.brain_context",
        "jarvis.domain.conversation_event_query",
        "jarvis.domain.conversation_event_search",
        "jarvis.domain.conversation_event_store",
        "jarvis.domain.conversation_events",
        "jarvis.domain.conversation_transcript",
        "jarvis.domain.explicit_address",
        "jarvis.domain.live_lifecycle",
        "jarvis.domain.output_disposition",
        "jarvis.domain.presentation_addressed_turn",
        "jarvis.domain.presentation_attention",
        "jarvis.domain.presentation_intent",
        "jarvis.domain.presentation_policy",
        "jarvis.domain.presentation_working_set",
        "jarvis.domain.reflex_policy",
        "jarvis.domain.speech_presentation",
        "jarvis.domain.v2",
        "jarvis.domain.voice_architecture",
        "jarvis.domain.voice_events",
        "jarvis.domain.voice_frontend",
        "jarvis.domain.voice_playback",
        "jarvis.domain.voice_state",
        "jarvis.domain.work_state",
        "jarvis.ports",
        "jarvis.ports.v2",
    }
)
